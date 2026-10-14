"""Where prices come from. CoinGecko for real, a deterministic mock for tests and offline use.

Prices are parsed straight into Decimal (json parse_float), never through float.
"""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

USER_AGENT = "crypto-helper (self-hosted)"


class ProviderError(Exception):
    """The price source couldn't answer. The message is safe to show and log."""


@dataclass(frozen=True)
class Quote:
    price: Decimal
    change_24h: Decimal | None  # percent


@dataclass(frozen=True)
class CoinInfo:
    coingecko_id: str
    symbol: str
    name: str


HttpGet = Callable[[str, dict, float], tuple[int, bytes]]


def _urllib_get(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class CoinGeckoProvider:
    name = "CoinGecko"
    attribution = "Price data by CoinGecko (coingecko.com)"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.coingecko.com/api/v3",
        timeout: float = 10,
        http_get: HttpGet = _urllib_get,
    ):
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._get = http_get
        self._coin_list: tuple[float, list[CoinInfo]] | None = None

    def _request(self, path: str, params: dict) -> bytes:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self._key:
            headers["x-cg-demo-api-key"] = self._key  # never logged
        url = f"{self._base}{path}?{urllib.parse.urlencode(params)}"
        try:
            status, body = self._get(url, headers, self._timeout)
        except (OSError, TimeoutError) as e:
            raise ProviderError(f"CoinGecko didn't answer ({e.__class__.__name__})") from None
        if status == 429:
            raise ProviderError("CoinGecko rate limit reached; try again in a minute")
        if status in (401, 403):
            raise ProviderError("CoinGecko refused the request (check BOT_COINGECKO_API_KEY)")
        if status != 200:
            raise ProviderError(f"CoinGecko answered HTTP {status}")
        return body

    def fetch(self, ids: list[str], fiats: list[str]) -> dict[str, dict[str, Quote]]:
        body = self._request(
            "/simple/price",
            {
                "ids": ",".join(ids),
                "vs_currencies": ",".join(fiats),
                "include_24hr_change": "true",
            },
        )
        try:
            data = json.loads(body, parse_float=Decimal, parse_int=Decimal)
        except ValueError:
            raise ProviderError("CoinGecko sent something that isn't JSON") from None
        if not isinstance(data, dict):
            raise ProviderError("CoinGecko sent an unexpected answer")
        out: dict[str, dict[str, Quote]] = {}
        for cid, row in data.items():
            if cid not in ids or not isinstance(row, dict):
                continue
            quotes = {}
            for fiat in fiats:
                price = row.get(fiat)
                if isinstance(price, Decimal) and price >= 0:
                    change = row.get(f"{fiat}_24h_change")
                    quotes[fiat] = Quote(price, change if isinstance(change, Decimal) else None)
            if quotes:
                out[cid] = quotes
        return out

    def coin_list(self) -> list[CoinInfo]:
        """Every coin CoinGecko knows (about 20,000), cached for a day."""
        if self._coin_list and time.monotonic() - self._coin_list[0] < 86400:
            return self._coin_list[1]
        try:
            rows = json.loads(self._request("/coins/list", {}))
        except ValueError:
            raise ProviderError("CoinGecko sent something that isn't JSON") from None
        coins = [
            CoinInfo(r["id"], str(r.get("symbol", "")), str(r.get("name", "")))
            for r in rows
            if isinstance(r, dict) and "id" in r
        ]
        self._coin_list = (time.monotonic(), coins)
        return coins


class MockProvider:
    """Deterministic fake prices: the same coin always has the same price. For tests,
    demos and offline practice (BOT_PRICE_PROVIDER=mock)."""

    name = "Mock (not real prices)"
    attribution = "Practice prices, not real market data"
    COINS = [
        CoinInfo("mockcoin", "mock", "Mock Coin"),
        CoinInfo("fake-one", "fake", "Fake One"),
        CoinInfo("fake-two", "fake", "Fake Two"),
    ]

    def __init__(self):
        self.fail_with: str | None = None  # tests set this to simulate an outage
        self.calls = 0

    def fetch(self, ids: list[str], fiats: list[str]) -> dict[str, dict[str, Quote]]:
        self.calls += 1
        if self.fail_with:
            raise ProviderError(self.fail_with)
        rates = {
            "usd": Decimal(1),
            "eur": Decimal("0.9"),
            "gbp": Decimal("0.8"),
            "jpy": Decimal(150),
            "cad": Decimal("1.35"),
            "aud": Decimal("1.5"),
        }
        out = {}
        for cid in ids:
            h = int.from_bytes(hashlib.sha256(cid.encode()).digest()[:4], "big")
            usd = Decimal(h % 100000) / 100 + Decimal("0.01")
            change = Decimal((h >> 8) % 2001 - 1000) / 100  # -10.00 .. +10.00 %
            out[cid] = {f: Quote(usd * rates[f], change) for f in fiats if f in rates}
        return out

    def coin_list(self) -> list[CoinInfo]:
        from app.prices.catalog import BUILTIN_COINS

        return [CoinInfo(cid, s.lower(), n) for s, (cid, n) in BUILTIN_COINS.items()] + self.COINS


def make_provider(settings):
    if settings.price_provider == "mock":
        return MockProvider()
    if settings.price_provider == "coingecko":
        return CoinGeckoProvider(
            api_key=settings.coingecko_api_key or None,
            base_url=settings.coingecko_base_url,
            timeout=settings.price_timeout_seconds,
        )
    raise SystemExit(
        f"Unknown BOT_PRICE_PROVIDER {settings.price_provider!r}: use coingecko or mock"
    )
