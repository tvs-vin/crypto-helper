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

READ_ENDPOINTS = {
    "/0/public/Assets",
    "/0/public/AssetPairs",
    "/0/private/BalanceEx",
    "/0/private/WithdrawMethods",
    "/0/private/TradesHistory",
}
TRADE_PAGES = 40  # 50 trades each; the rest comes on the next import
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

    def private(self, creds: dict, path: str, allow_denied=False, params=None):
        assert path in READ_ENDPOINTS and path.startswith("/0/private/")
        key, secret = creds.get("key", "").strip(), creds.get("secret", "").strip()
        try:
            base64.b64decode(secret, validate=True)
        except ValueError:
            raise SourceError(
                "The private key isn't what Kraken gives (base64 text)", final=True
            ) from None
        nonce = self._nonce()
        body = urllib.parse.urlencode({"nonce": nonce, **(params or {})})
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

    def pairs(self) -> dict[str, tuple[str, str]]:
        """Pair keys -> (base, quote) as coin codes (XXBTZUSD -> (XBT, USD)), cached a day."""
        now = time.monotonic()
        cached = getattr(self, "_pairs", None)
        if cached and now - cached[0] < ASSET_CACHE_SECONDS:
            return cached[1]
        names = self.assets()
        result = self._result(http.call(self.name, "GET", self.base + "/0/public/AssetPairs"))
        pairs = {}
        for key, p in (result or {}).items():
            base = names.get(p.get("base"), p.get("base", "")).split(".")[0].upper()
            quote = names.get(p.get("quote"), p.get("quote", "")).split(".")[0].upper()
            if base and quote:
                pairs[key] = (base, quote)
                pairs[str(p.get("altname", key))] = (base, quote)
        self._pairs = (now, pairs)
        return pairs

    def trades(self, creds: dict, state: dict, assets: set[str]):
        """Spot trades, newest first, paged backwards by trade ID (Kraken's own way to page);
        later imports start from the newest one seen. Margin trades aren't imported."""
        pairs = self.pairs()
        # A long history takes several imports: carry on backwards from where the last stopped
        # (`end` is inclusive, and that trade was imported last time).
        newest = state.get("pending_newest", state.get("since"))
        end = state.get("back_end")
        rows, seen = [], {end} if end else set()
        for _ in range(TRADE_PAGES):
            params = {}
            if state.get("since"):
                params["start"] = int(state["since"]) - 1  # exclusive; repeats are dropped
            if end:
                params["end"] = end
            result = self.private(
                creds, "/0/private/TradesHistory", allow_denied=True, params=params
            )
            if result is None:
                raise SourceError(
                    f"This key can't read trade history: on Kraken, tick {self.trades_permission}",
                    final=True,
                )
            page = result.get("trades") or {}
            fresh = {k: v for k, v in page.items() if k not in seen}
            for txid, t in fresh.items():
                seen.add(txid)
                newest = max(newest or 0, int(float(t["time"])))  # skipped ones too: not again
                if t.get("margin") and amount(t["margin"]) != 0:
                    continue
                base, quote = pairs.get(t.get("pair", ""), ("", ""))
                if not base:
                    continue
                rows.append(
                    TradeRow(
                        trade_id=txid,
                        order_id=t.get("ordertxid"),
                        time=parse_time(t["time"]),
                        base=self.aliases.get(base, base),
                        quote=self.aliases.get(quote, quote),
                        side="buy" if t.get("type") == "buy" else "sell",
                        amount=amount(t.get("vol", "0")),
                        price=amount(t.get("price", "0")),
                        total=amount(t.get("cost", "0")),
                        fee=amount(t.get("fee", "0")),
                        fee_asset=self.aliases.get(quote, quote),
                    )
                )
            if len(page) < 50 or not fresh:
                return rows, {"since": newest}
            end = min(fresh, key=lambda k: float(fresh[k]["time"]))  # inclusive: dropped above
        # Unfinished: next time, carry on backwards from `end`; new trades are picked up after.
        return rows, {"since": state.get("since"), "back_end": end, "pending_newest": newest}

    def check(self, creds: dict) -> Check:
        if self.private(creds, "/0/private/WithdrawMethods", allow_denied=True) is not None:
            return Check(False, "Kraken answered a withdrawal question, so this key can withdraw")
        if self.private(creds, "/0/private/BalanceEx", allow_denied=True) is None:
            raise SourceError("This key can't read balances: tick Funds → Query", final=True)
        return Check(None, "Kraken can't tell the app whether a key may trade; it can't withdraw")

    def check_trading(self, creds: dict) -> TradeCheck:
        if self.private(creds, "/0/private/WithdrawMethods", allow_denied=True) is not None:
            return TradeCheck(None, True, None, "Kraken answered a withdrawal question")
        if self.private(creds, "/0/private/BalanceEx", allow_denied=True) is None:
            raise SourceError("This key can't read balances: tick Funds → Query", final=True)
        # Kraken can't report the trade permission: the first tiny order checks it (13d).
        return TradeCheck(None, False, None, "it can't withdraw (checked with Kraken)")

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
        trading_confirm_text=(
            "On Kraken, this key has Funds → Query and Orders & trades → Query, "
            "Create & modify, and Cancel & close orders ticked, and nothing under "
            "Withdraw, Deposit or Earn."
        ),
        confirm_text="On Kraken, this key has only Funds → Query and Orders & trades → Query "
        "closed orders & trades ticked (nothing that creates or cancels orders, deposits or "
        "withdraws).",
        aliases={"XBT": "BTC", "XDG": "DOGE"},
        trades_permission="Orders and trades → Query closed orders & trades",
    )
)
