"""Kraken (Spot REST API), read-only.

A key and a base64 private key; each private request is signed with HMAC-SHA512 over the path
and SHA256(nonce + body). Kraken can't report a key's permissions, so the check does what it
can without doing anything: `WithdrawMethods` (a read-only list) only answers keys that may
withdraw, so an answer means the key is refused. Whether a key may trade can't be seen (that
would need an order call, which isn't in this code), so the owner confirms it.

Only these calls exist here: the asset list (public), BalanceEx, and WithdrawMethods.
"""

import base64
import hashlib
import hmac
import threading
import time
import urllib.parse

from app.sync import Check, Exchange, Fetched, Field, SourceError, http, register
from app.sync.http import amount

READ_ENDPOINTS = {"/0/public/Assets", "/0/private/BalanceEx", "/0/private/WithdrawMethods"}
ASSET_CACHE_SECONDS = 86400
DENIED = "EGeneral:Permission denied"


def sign(path: str, body: str, nonce: str, secret_b64: str) -> str:
    digest = hashlib.sha256((nonce + body).encode()).digest()
    mac = hmac.new(base64.b64decode(secret_b64), path.encode() + digest, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


class Kraken(Exchange):
    base = "https://api.kraken.com"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._lock = threading.Lock()
        self._last_nonce = 0
        self._assets: tuple[float, dict[str, str]] | None = None

    def _nonce(self) -> str:
        with self._lock:  # strictly increasing, even for two calls in the same millisecond
            self._last_nonce = max(self._last_nonce + 1, int(time.time() * 1000))
            return str(self._last_nonce)

    def _result(self, data, allow_denied=False):
        errors = (data.get("error") or []) if isinstance(data, dict) else ["EGeneral:Bad answer"]
        if errors:
            text = ", ".join(map(str, errors))[:200]
            if allow_denied and DENIED in text:
                return None
            if "Invalid key" in text or "Invalid signature" in text or DENIED in text:
                raise SourceError(f"Kraken refused the key: {text}", final=True)
            raise SourceError(f"Kraken said: {text}")
        return data.get("result")

    def private(self, creds: dict, path: str, allow_denied=False):
        assert path in READ_ENDPOINTS and path.startswith("/0/private/")
        key, secret = creds.get("key", "").strip(), creds.get("secret", "").strip()
        try:
            base64.b64decode(secret, validate=True)
        except ValueError:
            raise SourceError(
                "The private key isn't what Kraken gives (base64 text)", final=True
            ) from None
        nonce = self._nonce()
        body = urllib.parse.urlencode({"nonce": nonce})
        headers = {
            "API-Key": key,
            "API-Sign": sign(path, body, nonce, secret),
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }
        data = http.call(self.name, "POST", self.base + path, headers=headers, body=body.encode())
        return self._result(data, allow_denied)

    def assets(self) -> dict[str, str]:
        """Kraken's asset keys -> their names (XXBT -> XBT), cached for a day."""
        now = time.monotonic()
        if self._assets and now - self._assets[0] < ASSET_CACHE_SECONDS:
            return self._assets[1]
        result = self._result(http.call(self.name, "GET", self.base + "/0/public/Assets"))
        names = {k: str(v.get("altname") or k) for k, v in (result or {}).items()}
        self._assets = (now, names)
        return names

    def check(self, creds: dict) -> Check:
        if self.private(creds, "/0/private/WithdrawMethods", allow_denied=True) is not None:
            return Check(False, "Kraken answered a withdrawal question, so this key can withdraw")
        if self.private(creds, "/0/private/BalanceEx", allow_denied=True) is None:
            raise SourceError("This key can't read balances: tick Funds → Query", final=True)
        return Check(None, "Kraken can't tell the app whether a key may trade; it can't withdraw")

    def fetch(self, creds: dict) -> Fetched:
        names = self.assets()
        out = Fetched()
        for asset, entry in (self.private(creds, "/0/private/BalanceEx") or {}).items():
            # Staked and earning balances (XTZ.S, DOT.F…) count towards the coin itself.
            code = names.get(asset, asset).split(".")[0].upper()
            total = amount(entry.get("balance", "0") if isinstance(entry, dict) else entry)
            if total:
                out.balances[code] = out.balances.get(code, 0) + total
        return out


KRAKEN = register(
    Kraken(
        id="kraken",
        name="Kraken",
        fields=[
            Field("key", "API key", secret=False),
            Field("secret", "Private key", help="The long text Kraken shows once, ending in ==."),
        ],
        guide="guides/exchange-connections#kraken",
        confirm_text="On Kraken, this key has only Funds → Query and Orders & trades → Query "
        "closed orders & trades ticked (nothing that creates or cancels orders, deposits or "
        "withdraws).",
        aliases={"XBT": "BTC", "XDG": "DOGE"},
    )
)
