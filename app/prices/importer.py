"""Importing past prices onto the charts (12b), from Coinbase's public price history.

For each coin and currency Coinbase trades it in (BTC-USD, BTC-EUR, ...):
- daily candles, as far back as Coinbase has them (daily_candles; USD ones also feed trend
  signals and are kept up to date by app.prices.daily by themselves);
- hourly candles for the last HOURLY_DAYS days (price_candles, source "coinbase"), only for the
  time before this server recorded anything for that coin and currency.

Runs in a thread, one import at a time, never holding the database while Coinbase answers. The
last result is kept in app_settings so it survives a restart.
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.db import IMMEDIATE
from app.models import AppSetting, DailyCandle, PriceCandle, PricePoint
from app.money import format_amount
from app.prices import daily
from app.prices.catalog import all_coins
from app.sync import SourceError

log = logging.getLogger(__name__)

HOURLY_DAYS = 90
HOUR_PAGE = 299  # hours per request (Coinbase answers at most 300 candles)
SETTINGS_KEY = "price_import"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0)


class PriceImport:
    def __init__(self, session_factory, base_url: str):
        self.factory = session_factory
        self.base_url = base_url
        self.client = daily.Coinbase(base_url)
        self._lock = threading.Lock()
        self.progress = {"running": False, "done": 0, "total": 0, "current": None}
        self.now = _now
        self.hub = None  # set by the app: charts and Settings follow the import

    # ---- running -----------------------------------------------------------------------------

    def start(self, symbols: list[str] | None, fiats: list[str], actor: str) -> bool:
        """Start an import in the background; False if one is already running."""
        with self._lock:
            if self.progress["running"]:
                return False
            self.progress = {"running": True, "done": 0, "total": 0, "current": "starting"}
        threading.Thread(target=self.run, args=(symbols, fiats, actor), daemon=True).start()
        return True

    def run(self, symbols: list[str] | None, fiats: list[str], actor: str) -> dict:
        result = {"days": 0, "hours": 0, "skipped": [], "errors": {}, "by": actor}
        try:
            with self.factory() as db:
                coins = all_coins(db)
            wanted = [s for s in (symbols or sorted(coins)) if s in coins]
            try:
                markets = self.client.markets()
            except SourceError as e:
                result["errors"]["Coinbase"] = str(e)
                return self._finish(result)
            tasks = []
            for s in wanted:
                for f in fiats:
                    if (s, f.upper()) in markets:
                        tasks.append((s, f))
                    else:
                        result["skipped"].append(f"{s}-{f.upper()}")
            self.progress["total"] = len(tasks)
            for s, f in tasks:
                self.progress["current"] = f"{s} in {f.upper()}"
                try:
                    result["days"] += self._days(s, f)
                    result["hours"] += self._hours(s, f, coins[s].coingecko_id)
                except SourceError as e:
                    result["errors"][f"{s}-{f.upper()}"] = str(e)
                self.progress["done"] += 1
                self._tell()
        except Exception as e:  # report it rather than leaving "running" forever
            log.exception("price import failed")
            result["errors"]["import"] = type(e).__name__
        return self._finish(result)

    def _finish(self, result: dict) -> dict:
        result["finished_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
        with self.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            row = db.get(AppSetting, SETTINGS_KEY)
            if row is None:
                db.add(AppSetting(key=SETTINGS_KEY, value=result, updated_by=result["by"]))
            else:
                row.value, row.updated_by = result, result["by"]
            db.commit()
        self.progress = {"running": False, "done": 0, "total": 0, "current": None}
        self._tell()
        log.info("price import: %s days, %s hours, %s errors", result["days"], result["hours"],
                 len(result["errors"]))  # fmt: skip
        return result

    def _tell(self) -> None:
        from app import live

        live.publish(self.hub, self.factory, ["prices"])

    def _days(self, symbol: str, fiat: str) -> int:
        job = daily.DailyPriceJob(self.factory, self.base_url, today=lambda: self.now().date())
        with self.factory() as db:
            last = db.scalar(
                select(func.max(DailyCandle.day)).where(
                    DailyCandle.symbol == symbol, DailyCandle.quote == fiat
                )
            )
        return job.update(symbol, last, fiat)

    def _hours(self, symbol: str, fiat: str, cid: str) -> int:
        """Hourly candles for the last HOURLY_DAYS days, before anything recorded here."""
        with self.factory() as db:
            firsts = [
                db.scalar(
                    select(func.min(PriceCandle.start)).where(
                        PriceCandle.coingecko_id == cid,
                        PriceCandle.fiat == fiat,
                        PriceCandle.source == "recorded",
                    )
                ),
                db.scalar(
                    select(func.min(PricePoint.at)).where(
                        PricePoint.coingecko_id == cid, PricePoint.fiat == fiat
                    )
                ),
            ]
        end = min([t for t in firsts if t is not None], default=self.now())
        start = self.now() - timedelta(days=HOURLY_DAYS)
        added = 0
        t = start
        while t < end:
            stop = min(t + timedelta(hours=HOUR_PAGE), end)
            rows = self.client.candles(symbol, t, stop, fiat, granularity=3600)
            added += self._store_hours(cid, fiat, [r for r in rows if r[0] < end])
            t = stop
            time.sleep(daily.PAUSE)
        return added

    def _store_hours(self, cid: str, fiat: str, rows) -> int:
        if not rows:
            return 0
        with self.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            have = set(
                db.scalars(
                    select(PriceCandle.start).where(
                        PriceCandle.coingecko_id == cid,
                        PriceCandle.fiat == fiat,
                        PriceCandle.interval_minutes == 60,
                        PriceCandle.start >= rows[0][0],
                        PriceCandle.start <= rows[-1][0],
                    )
                )
            )
            n = 0
            for at, o, h, lo, c in rows:
                if at in have:
                    continue  # recorded (or already imported): never replaced
                db.add(PriceCandle(coingecko_id=cid, fiat=fiat, interval_minutes=60, start=at,
                                   open=format_amount(o), high=format_amount(h),
                                   low=format_amount(lo), close=format_amount(c), points=0,
                                   source="coinbase"))  # fmt: skip
                n += 1
            db.commit()
        return n

    # ---- reading and removing ----------------------------------------------------------------

    def last(self, db) -> dict | None:
        row = db.get(AppSetting, SETTINGS_KEY)
        return dict(row.value) if row else None

    @staticmethod
    def coverage(db) -> dict:
        """symbol -> currency -> {first_day, days, first_hour, hours}."""
        out: dict = {}
        for sym, quote, first, n in db.execute(
            select(
                DailyCandle.symbol, DailyCandle.quote, func.min(DailyCandle.day), func.count()
            ).group_by(DailyCandle.symbol, DailyCandle.quote)
        ):
            out.setdefault(sym, {})[quote] = {"first_day": first, "days": n, "first_hour": None,
                                              "hours": 0}  # fmt: skip
        ids = {c.coingecko_id: s for s, c in all_coins(db).items()}
        for cid, fiat, first, n in db.execute(
            select(PriceCandle.coingecko_id, PriceCandle.fiat, func.min(PriceCandle.start),
                   func.count())
            .where(PriceCandle.source == "coinbase")
            .group_by(PriceCandle.coingecko_id, PriceCandle.fiat)
        ):  # fmt: skip
            sym = ids.get(cid)
            if sym:
                entry = out.setdefault(sym, {}).setdefault(
                    fiat, {"first_day": None, "days": 0, "first_hour": None, "hours": 0}
                )
                entry.update(first_hour=first, hours=n)
        return out

    @staticmethod
    def remove(db) -> dict:
        """Delete imported prices. USD daily prices stay: trend signals use them, and they're
        downloaded again by themselves anyway."""
        hours = db.execute(delete(PriceCandle).where(PriceCandle.source == "coinbase")).rowcount
        days = db.execute(delete(DailyCandle).where(DailyCandle.quote != "usd")).rowcount
        return {"hours": hours, "days": days}
