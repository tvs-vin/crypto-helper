"""Daily prices (12a): each coin's open/high/low/close per day in USD, from Coinbase's public
price history (no key, 300 days per request). Downloaded once, years back, then topped up; used
for trend signals now, and the backtester and charts later.

Only coins with a Coinbase USD market (matched by symbol) get daily prices. Fetching happens
with no database session open; each page is written in its own short transaction.
"""

import asyncio
import logging
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db import IMMEDIATE
from app.models import DailyCandle
from app.money import format_amount
from app.prices.catalog import all_coins
from app.sync import SourceError
from app.sync.http import amount, call

log = logging.getLogger(__name__)

PAGE_DAYS = 299  # Coinbase answers at most 300 candles; start and end both count
MAX_PAGES = 25  # about 20 years back
PAUSE = 0.2  # between requests: well under Coinbase's public rate limit
REFRESH_SECONDS = 3600
TICK_SECONDS = 60
NAME = "Coinbase"


class Coinbase:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def markets(self) -> set[tuple[str, str]]:
        """(coin, currency) pairs Coinbase trades and hasn't delisted, e.g. ("BTC", "EUR")."""
        rows = call(NAME, "GET", f"{self.base}/products")
        if not isinstance(rows, list):
            raise SourceError("Coinbase's market list wasn't a list")
        return {
            (str(p.get("base_currency", "")).upper(), str(p.get("quote_currency", "")).upper())
            for p in rows
            if isinstance(p, dict) and p.get("status") != "delisted"
        }

    def products(self) -> set[str]:
        """Coins with a USD market."""
        return {base for base, quote in self.markets() if quote == "USD"}

    def candles(
        self, symbol: str, start, end, quote: str = "USD", granularity: int = 86400
    ) -> list[tuple]:
        """(day or hour, open, high, low, close) for start..end, oldest first. Days for the
        daily granularity (start/end are dates), naive UTC datetimes for hours."""

        def stamp(t):
            return (
                f"{t.isoformat()}T00:00:00Z"
                if not isinstance(t, datetime)
                else (f"{t.replace(microsecond=0).isoformat()}Z")
            )

        url = (
            f"{self.base}/products/{symbol}-{quote.upper()}/candles?granularity={granularity}"
            f"&start={stamp(start)}&end={stamp(end)}"
        )
        rows = call(NAME, "GET", url)
        if not isinstance(rows, list):
            raise SourceError("Coinbase's price history wasn't a list")
        out = []
        for r in rows:
            if not isinstance(r, list) or len(r) < 5:
                raise SourceError("Coinbase sent a price row that doesn't fit")
            # [time, low, high, open, close, volume]
            at = datetime.fromtimestamp(int(r[0]), UTC).replace(tzinfo=None)
            day = at.date() if granularity == 86400 else at
            low, high, open_, close = (amount(v) for v in r[1:5])
            if min(low, high, open_, close) <= 0:
                continue
            out.append((day, open_, high, low, close))
        return sorted(out)


def store(db: DbSession, symbol: str, rows, quote: str = "usd") -> int:
    """Insert or update days (today's candle changes until the day is over)."""
    days = [r[0] for r in rows]
    if not days:
        return 0
    have = {
        c.day: c
        for c in db.scalars(
            select(DailyCandle).where(
                DailyCandle.symbol == symbol,
                DailyCandle.quote == quote,
                DailyCandle.day >= min(days),
                DailyCandle.day <= max(days),
            )
        )
    }
    n = 0
    for day, o, h, lo, c in rows:
        values = dict(open=format_amount(o), high=format_amount(h), low=format_amount(lo),
                      close=format_amount(c))  # fmt: skip
        row = have.get(day)
        if row is None:
            db.add(DailyCandle(symbol=symbol, quote=quote, day=day, source="coinbase", **values))
            n += 1
        else:
            for k, v in values.items():
                setattr(row, k, v)
    return n


def coverage(db: DbSession, quote: str = "usd") -> dict[str, dict]:
    rows = db.execute(
        select(
            DailyCandle.symbol,
            func.min(DailyCandle.day),
            func.max(DailyCandle.day),
            func.count(),
        )
        .where(DailyCandle.quote == quote)
        .group_by(DailyCandle.symbol)
    ).all()
    return {s: {"first": a, "last": b, "days": n} for s, a, b, n in rows}


def recent(db: DbSession, symbol: str, days: int, quote: str = "usd") -> list[DailyCandle]:
    """The last `days` days, oldest first."""
    rows = db.scalars(
        select(DailyCandle)
        .where(DailyCandle.symbol == symbol, DailyCandle.quote == quote)
        .order_by(DailyCandle.day.desc())
        .limit(days)
    ).all()
    return list(reversed(rows))


def moving_average(closes: list[Decimal]) -> Decimal | None:
    return sum(closes, Decimal(0)) / len(closes) if closes else None


class DailyPriceJob:
    """Keeps daily prices current: the full history the first time, then the latest days."""

    def __init__(self, session_factory, base_url: str, today=None):
        self.factory = session_factory
        self.client = Coinbase(base_url)
        self._last: float | None = None  # never yet (monotonic time starts at boot, not 0)
        self.today = today or (lambda: datetime.now(UTC).date())
        self.last_result: dict = {}

    def _write(self, symbol: str, rows, quote: str = "usd") -> int:
        with self.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            n = store(db, symbol, rows, quote)
            db.commit()
            return n

    def update(self, symbol: str, since: date | None, quote: str = "usd") -> int:
        """Fetch from `since` (None: as far back as Coinbase has) to today; returns new days."""
        today = self.today()
        added = 0
        if since is not None:
            rows = self.client.candles(symbol, since, today, quote)
            return self._write(symbol, rows, quote)
        end = today
        for _ in range(MAX_PAGES):
            start = end - timedelta(days=PAGE_DAYS)
            rows = self.client.candles(symbol, start, end, quote)
            if not rows:
                break  # before the coin was listed
            added += self._write(symbol, rows, quote)
            end = start - timedelta(days=1)
            time.sleep(PAUSE)
        return added

    def tick(self, force: bool = False) -> dict:
        if not force and self._last is not None and time.monotonic() - self._last < REFRESH_SECONDS:
            return {"skipped": "not due"}
        with self.factory() as db:
            symbols = sorted(all_coins(db))
            have = {s: c["last"] for s, c in coverage(db).items()}
        result: dict = {"added": {}, "errors": {}}
        try:
            listed = self.client.products()
        except SourceError as e:
            self.last_result = {"skipped": str(e)}
            return self.last_result
        result["missing"] = [s for s in symbols if s not in listed]
        for symbol in symbols:
            if symbol not in listed:
                continue
            try:
                n = self.update(symbol, have.get(symbol))
            except SourceError as e:
                result["errors"][symbol] = str(e)
                continue
            if n:
                result["added"][symbol] = n
            time.sleep(PAUSE)
        self._last = time.monotonic()
        self.last_result = result
        if result["added"]:
            log.info("daily prices: %s", result["added"])
        return result

    async def run_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # one bad pass must never stop the updates for good
                log.exception("daily prices update failed")
            await asyncio.sleep(TICK_SECONDS)
