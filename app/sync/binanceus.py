"""Binance.US, read-only.

A key and secret; signed requests carry a timestamp and an HMAC-SHA256 of the query string.
Binance.US's documentation has no call that reports a key's permissions. Binance's own
read-only "API key restrictions" call is tried: if Binance.US answers it, a key that may trade
or withdraw is refused; if not, the owner confirms (the flags in the account answer describe
the account, not the key).

Only these calls exist here: the key's restrictions, and the account (balances).
"""

import hashlib
import hmac
import time
import urllib.parse

from app.sync import Check, Exchange, Fetched, Field, SourceError, TradeRow, http, register
from app.sync.http import amount, parse_time

READ_ENDPOINTS = {
    "/sapi/v1/account/apiRestrictions",
    "/api/v3/account",
    "/api/v3/exchangeInfo",
    "/api/v3/myTrades",
}
TRADES_PER_CALL = 1000
MAX_CALLS = 60  # each myTrades call weighs 20 of Binance's 1200 a minute
RISKY_FLAGS = (
    "enableWithdrawals",
    "enableSpotAndMarginTrading",
    "enableMargin",
    "enableFutures",
    "enableInternalTransfer",
    "permitsUniversalTransfer",
    "enableVanillaOptions",
    "enablePortfolioMarginTrading",
)


def sign(query: str, secret: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


class BinanceUS(Exchange):
    base = "https://api.binance.us"

    def signed(self, creds: dict, path: str, final_on=(401,), params=None):
        assert path in READ_ENDPOINTS
        query = urllib.parse.urlencode(
            {**(params or {}), "recvWindow": 5000, "timestamp": int(time.time() * 1000)}
        )
        query += "&signature=" + sign(query, creds.get("secret", "").strip())
        headers = {"X-MBX-APIKEY": creds.get("key", "").strip()}
        return http.call(
            self.name, "GET", f"{self.base}{path}?{query}", headers=headers, final_on=final_on
        )

    def check(self, creds: dict) -> Check:
        try:
            r = self.signed(creds, "/sapi/v1/account/apiRestrictions", final_on=())
        except SourceError:
            r = None  # not answered on Binance.US: see below
        if isinstance(r, dict) and "enableReading" in r:
            if any(r.get(flag) for flag in RISKY_FLAGS):
                return Check(False, "Binance.US says this key can trade or withdraw")
            return Check(True, "Reading only (checked with Binance.US)")
        self.signed(creds, "/api/v3/account")  # the key works and can read
        return Check(None, "Binance.US doesn't let the app see a key's permissions")

    def fetch(self, creds: dict) -> Fetched:
        out = Fetched()
        account = self.signed(creds, "/api/v3/account")
        for b in (account or {}).get("balances", []):
            code = str(b.get("asset", "")).upper()
            total = amount(b.get("free", "0")) + amount(b.get("locked", "0"))
            if code and total:
                out.balances[code] = out.balances.get(code, 0) + total
        return out

    def trades(self, creds: dict, state: dict, assets: set[str]):
        """Binance.US lists trades per market: every market whose coin is tracked or held, each
        from the trade after the last one imported."""
        info = http.call(self.name, "GET", self.base + "/api/v3/exchangeInfo")
        markets = sorted(
            (s["symbol"], s["baseAsset"].upper(), s["quoteAsset"].upper())
            for s in (info or {}).get("symbols", [])
            if str(s.get("baseAsset", "")).upper() in assets
        )
        rows, state, calls = [], dict(state), 0
        for symbol, base, quote in markets:
            while calls < MAX_CALLS:
                calls += 1
                page = self.signed(
                    creds,
                    "/api/v3/myTrades",
                    params={
                        "symbol": symbol,
                        "fromId": int(state.get(symbol, 0)),
                        "limit": TRADES_PER_CALL,
                    },
                )
                for t in page or []:
                    rows.append(
                        TradeRow(
                            trade_id=f"{symbol}:{t['id']}",
                            order_id=str(t.get("orderId") or ""),
                            time=parse_time(t["time"]),
                            base=base,
                            quote=quote,
                            side="buy" if t.get("isBuyer") else "sell",
                            amount=amount(t["qty"]),
                            price=amount(t["price"]),
                            total=amount(t.get("quoteQty", "0")),
                            fee=amount(t.get("commission", "0")),
                            fee_asset=str(t.get("commissionAsset") or quote).upper(),
                        )
                    )
                if page:
                    state[symbol] = max(int(t["id"]) for t in page) + 1
                if len(page or []) < TRADES_PER_CALL:
                    break
        return rows, state


BINANCEUS = register(
    BinanceUS(
        id="binanceus",
        name="Binance.US",
        fields=[Field("key", "API key", secret=False), Field("secret", "Secret key")],
        guide="guides/exchange-connections#binanceus",
        confirm_text="On Binance.US, this key has only Enable Reading ticked (no trading, no "
        "withdrawals).",
        trades_permission="Enable Reading",
    )
)
