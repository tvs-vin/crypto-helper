"""Gemini, read-only.

A key and secret; each private request carries a base64 JSON payload and its HMAC-SHA384.
Gemini reports a key's roles: only an Auditor key (read-only, and Gemini doesn't let it be
combined with other roles) is accepted; Trader or Fund Manager is refused.

Only these calls exist here: the key's roles, and balances.
"""

import base64
import hashlib
import hmac
import json
import threading
import time

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

READ_ENDPOINTS = {"/v1/roles", "/v1/balances", "/v1/symbols", "/v1/mytrades"}
# Quote currencies, longest first: a symbol is <base><quote> (btcusd, ethbtc, solgusd).
QUOTES = (
    "gusd",
    "usdt",
    "usdc",
    "rlusd",
    "usd",
    "btc",
    "eth",
    "dai",
    "eur",
    "gbp",
    "sgd",
    "aud",
    "cad",
)
TRADES_PER_CALL = 500
MAX_CALLS = 60


def sign(payload_b64: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload_b64, hashlib.sha384).hexdigest()


class Gemini(Exchange):
    base = "https://api.gemini.com"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._lock = threading.Lock()
        self._last_nonce = 0

    def _nonce(self) -> str:
        with self._lock:
            self._last_nonce = max(self._last_nonce + 1, int(time.time() * 1000))
            return str(self._last_nonce)

    def private(self, creds: dict, path: str, **extra):
        assert path in READ_ENDPOINTS
        body = {"request": path, "nonce": self._nonce(), **extra}
        payload = base64.b64encode(json.dumps(body).encode())
        headers = {
            "Content-Type": "text/plain",
            "Content-Length": "0",
            "Cache-Control": "no-cache",
            "X-GEMINI-APIKEY": creds.get("key", "").strip(),
            "X-GEMINI-PAYLOAD": payload.decode(),
            "X-GEMINI-SIGNATURE": sign(payload, creds.get("secret", "").strip()),
        }
        return http.call(self.name, "POST", self.base + path, headers=headers, body=b"")

    def check(self, creds: dict) -> Check:
        roles = self.private(creds, "/v1/roles")
        if not isinstance(roles, dict):
            raise SourceError("Gemini didn't say what the key may do")
        if roles.get("isTrader") or roles.get("isFundManager"):
            return Check(False, "Gemini says this key is a Trader or Fund Manager key")
        if roles.get("isAuditor") is True:
            return Check(True, "Auditor (read-only), checked with Gemini")
        return Check(None, "Gemini didn't say this key is an Auditor key")

    def check_trading(self, creds: dict) -> TradeCheck:
        roles = self.private(creds, "/v1/roles")
        if not isinstance(roles, dict):
            raise SourceError("Gemini didn't say what the key may do")
        return TradeCheck(
            can_trade=bool(roles.get("isTrader")) and not roles.get("isAuditor"),
            can_withdraw=bool(roles.get("isFundManager")),  # Fund Manager moves funds
            ip_locked=None,  # not reported: the guide says to set the IP allowlist
            summary="checked with Gemini (Trader role, no Fund Manager)",
        )

    def fetch(self, creds: dict) -> Fetched:
        out = Fetched()
        for b in self.private(creds, "/v1/balances") or []:
            code = str(b.get("currency", "")).upper()
            total = amount(b.get("amount", "0"))
            if code and total:
                out.balances[code] = out.balances.get(code, 0) + total
        return out

    def trades(self, creds: dict, state: dict, assets: set[str]):
        """Gemini lists trades per market: every market whose coin is tracked or held. Each one
        is walked forward from where the last import stopped (Gemini's documented way)."""
        symbols = http.call(self.name, "GET", self.base + "/v1/symbols")
        wanted = [s for s in symbols if (split_symbol(s) or ("", ""))[0] in assets]
        rows, state, calls = [], dict(state), 0
        for symbol in sorted(wanted):
            base, quote = split_symbol(symbol)
            since = int(state.get(symbol, 0))
            while calls < MAX_CALLS:
                calls += 1
                page = (
                    self.private(
                        creds,
                        "/v1/mytrades",
                        symbol=symbol,
                        timestamp=since,
                        limit_trades=TRADES_PER_CALL,
                    )
                    or []
                )
                for t in page:
                    qty, price = amount(t.get("amount", "0")), amount(t.get("price", "0"))
                    rows.append(
                        TradeRow(
                            trade_id=f"{symbol}:{t.get('tid')}",
                            order_id=str(t.get("order_id") or ""),
                            time=parse_time(t.get("timestampms") or t.get("timestamp")),
                            base=base,
                            quote=quote,
                            side="buy" if str(t.get("type")).lower() == "buy" else "sell",
                            amount=qty,
                            price=price,
                            total=qty * price,
                            fee=amount(t.get("fee_amount", "0")),
                            fee_asset=str(t.get("fee_currency") or quote).upper(),
                        )
                    )
                if page:
                    since = max(int(t.get("timestampms") or 0) for t in page) + 1
                    state[symbol] = since
                if len(page) < TRADES_PER_CALL:
                    break
        return rows, state


def split_symbol(symbol: str) -> tuple[str, str] | None:
    s = symbol.lower()
    for q in sorted(QUOTES, key=len, reverse=True):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)].upper(), q.upper()
    return None


GEMINI = register(
    Gemini(
        id="gemini",
        name="Gemini",
        fields=[
            Field("key", "API key", secret=False, help="Starts with account-"),
            Field("secret", "API secret"),
        ],
        guide="guides/exchange-connections#gemini",
        trading_confirm_text=(
            "On Gemini, this key has the Trader role only (not Fund Manager or Auditor)."
        ),
        confirm_text="On Gemini, this key has only the Auditor role.",
        trades_permission="the Auditor role",
    )
)
