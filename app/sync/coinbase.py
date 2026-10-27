"""Coinbase (Advanced Trade API, CDP keys), read-only.

A key is a name (`organizations/…/apiKeys/…`) and an EC private key (ECDSA P-256; Coinbase's
Ed25519 keys don't work with this API). Each request carries a fresh JWT signed with it (ES256,
valid 2 minutes). Coinbase reports a key's permissions, so a key that can trade or transfer is
refused.

Only these calls exist here: the key's permissions, and the account list.
"""

import base64
import json
import re
import secrets
import time
import urllib.parse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app.sync import (
    Check,
    Exchange,
    Fetched,
    Field,
    SourceError,
    TradeCheck,
    TradeRow,
    http,
    register,
)
from app.sync.http import amount, parse_time

NAME_RE = re.compile(r"^organizations/[A-Za-z0-9-]+/apiKeys/[A-Za-z0-9-]+$")
READ_ENDPOINTS = {
    "/api/v3/brokerage/key_permissions",
    "/api/v3/brokerage/accounts",
    "/api/v3/brokerage/orders/historical/fills",
}
MAX_PAGES = 20


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Coinbase(Exchange):
    base = "https://api.coinbase.com"
    host = "api.coinbase.com"  # what the JWT names (no scheme)

    def _key(self, creds: dict):
        name = creds.get("key_name", "").strip()
        if not NAME_RE.match(name):
            raise SourceError("The API key name looks like organizations/…/apiKeys/…", final=True)
        pem = creds.get("private_key", "").strip().replace("\\n", "\n")
        try:
            key = serialization.load_pem_private_key(pem.encode(), password=None)
        except (ValueError, TypeError):
            raise SourceError(
                "The private key isn't a PEM key (it starts with -----BEGIN EC PRIVATE KEY-----)",
                final=True,
            ) from None
        if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
            raise SourceError(
                "This key type doesn't work with Coinbase's trading API: create the "
                "key with the ECDSA signature algorithm (not Ed25519)",
                final=True,
            )
        return name, key

    def jwt(self, creds: dict, method: str, path: str, now: int | None = None) -> str:
        name, key = self._key(creds)
        now = int(time.time()) if now is None else now
        header = {"alg": "ES256", "kid": name, "nonce": secrets.token_hex(16), "typ": "JWT"}
        claims = {
            "sub": name,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            "uri": f"{method} {self.host}{path}",
        }
        signing_input = (
            f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(claims).encode())}"
        )
        r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
        return f"{signing_input}.{_b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"

    def _get(self, creds: dict, path: str, query: str = ""):
        assert path in READ_ENDPOINTS
        token = self.jwt(creds, "GET", path)
        url = f"{self.base}{path}{'?' + query if query else ''}"
        return http.call(self.name, "GET", url, headers={"Authorization": f"Bearer {token}"})

    def check(self, creds: dict) -> Check:
        p = self._get(creds, "/api/v3/brokerage/key_permissions")
        if not isinstance(p, dict) or "can_view" not in p:
            raise SourceError("Coinbase didn't say what the key may do")
        if p.get("can_trade") or p.get("can_transfer"):
            return Check(False, "Coinbase says this key can trade or transfer")
        if not p.get("can_view"):
            raise SourceError("Coinbase says this key can't view balances: tick View", final=True)
        return Check(True, "View only (checked with Coinbase)")

    def check_trading(self, creds: dict) -> TradeCheck:
        p = self._get(creds, "/api/v3/brokerage/key_permissions")
        if not isinstance(p, dict) or "can_view" not in p:
            raise SourceError("Coinbase didn't say what the key may do")
        return TradeCheck(
            can_trade=bool(p.get("can_trade")) and bool(p.get("can_view")),
            can_withdraw=bool(p.get("can_transfer")),  # Coinbase: deposit/withdrawal rights
            ip_locked=None,  # not reported: the guide says to set the IP allowlist
            summary="checked with Coinbase",
        )

    def fetch(self, creds: dict) -> Fetched:
        out = Fetched()
        cursor = ""
        for _ in range(MAX_PAGES):
            query = "limit=250" + (f"&cursor={cursor}" if cursor else "")
            page = self._get(creds, "/api/v3/brokerage/accounts", query)
            for a in page.get("accounts", []):
                code = str(a.get("currency", "")).upper()
                total = amount((a.get("available_balance") or {}).get("value", "0")) + amount(
                    (a.get("hold") or {}).get("value", "0")
                )
                if code and total:
                    out.balances[code] = out.balances.get(code, 0) + total
            if not page.get("has_next"):
                return out
            cursor = str(page.get("cursor", ""))
            if not re.fullmatch(r"[A-Za-z0-9_=-]{1,200}", cursor):
                raise SourceError("Coinbase sent a page marker the app doesn't understand")
        raise SourceError(f"Coinbase listed more than {MAX_PAGES * 250} accounts")

    def trades(self, creds: dict, state: dict, assets: set[str]):
        """Spot fills, newest import first; later imports start after the newest one seen.
        Adjusted fills (reversals, corrections) aren't imported: the guide says so."""
        rows, newest = [], state.get("after")
        cursor = state.get("cursor", "")
        for _ in range(MAX_PAGES):
            query = "limit=250&product_types=SPOT"
            if state.get("after"):
                query += f"&start_sequence_timestamp={urllib.parse.quote(state['after'])}"
            if cursor:
                query += f"&cursor={urllib.parse.quote(cursor)}"
            page = self._get(creds, "/api/v3/brokerage/orders/historical/fills", query)
            for f in page.get("fills", []):
                if f.get("trade_type", "FILL") != "FILL":
                    continue
                base, _, quote = str(f.get("product_id", "")).upper().partition("-")
                price, size = amount(f.get("price", "0")), amount(f.get("size", "0"))
                if not (base and quote and price):
                    continue
                if f.get("size_in_quote"):  # sized in the quote currency
                    total, qty = size, size / price
                else:
                    total, qty = size * price, size
                when = str(f.get("trade_time") or f.get("sequence_timestamp"))
                rows.append(
                    TradeRow(
                        trade_id=str(f.get("trade_id") or f.get("entry_id")),
                        order_id=f.get("order_id"),
                        time=parse_time(when),
                        base=base,
                        quote=quote,
                        side="buy" if f.get("side") == "BUY" else "sell",
                        amount=qty,
                        price=price,
                        total=total,
                        fee=amount(f.get("commission", "0")),
                        fee_asset=quote,
                    )
                )
                newest = max(newest or when, when)
            cursor = str(page.get("cursor") or "")
            if not cursor or not page.get("fills"):
                return rows, {"after": newest}
        return rows, {"after": state.get("after"), "cursor": cursor}  # more next time

    def mask(self, creds: dict) -> str:
        name = creds.get("key_name", "")
        return f"Coinbase key …{name[-4:]}" if len(name) >= 8 else "Coinbase key"


COINBASE = register(
    Coinbase(
        id="coinbase",
        name="Coinbase",
        fields=[
            Field(
                "key_name",
                "API key name",
                secret=False,
                help="Looks like organizations/…/apiKeys/…",
            ),
            Field(
                "private_key",
                "Private key",
                multiline=True,
                help="Starts with -----BEGIN EC PRIVATE KEY-----. Paste all of it.",
            ),
        ],
        guide="guides/exchange-connections#coinbase",
        trading_confirm_text="On Coinbase, this key has View and Trade ticked, and not Transfer.",
        confirm_text="",
        trades_permission="View",
    )
)
