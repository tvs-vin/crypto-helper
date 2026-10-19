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

from app.sync import Check, Exchange, Fetched, Field, SourceError, http, register
from app.sync.http import amount

READ_ENDPOINTS = {"/sapi/v1/account/apiRestrictions", "/api/v3/account"}
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

    def signed(self, creds: dict, path: str, final_on=(401,)):
        assert path in READ_ENDPOINTS
        query = urllib.parse.urlencode({"recvWindow": 5000, "timestamp": int(time.time() * 1000)})
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


BINANCEUS = register(
    BinanceUS(
        id="binanceus",
        name="Binance.US",
        fields=[Field("key", "API key", secret=False), Field("secret", "Secret key")],
        guide="guides/exchange-connections#binanceus",
        confirm_text="On Binance.US, this key has only Enable Reading ticked (no trading, no "
        "withdrawals).",
    )
)
