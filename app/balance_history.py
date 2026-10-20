"""Balance history (milestone 11e): every wallet's balances and their value, over time.

A snapshot of every wallet is taken every hour (adjustable), and soon after balances change
(a sync, or a balance typed in). Each snapshot stores, per wallet and coin, the amount and its
value then in every currency that had a price. After `detail_days` they're compacted to one a
day (the day's last), kept forever unless `keep_days` says otherwise.

Values are fixed when recorded, so the chart shows what the portfolio was worth then. Nothing
is recorded while prices are stale or practice prices are on (made-up values would mix in).
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as DbSession

from app import features, money
from app.db import IMMEDIATE
from app.models import AppSetting, BalancePoint, BalanceSnapshot, Holding, Wallet
from app.prices.catalog import FIATS, all_coins
from app.prices.service import PricesUnavailable
from app.prices.valuation import round_fiat, value
from app.timeutil import utcnow

log = logging.getLogger(__name__)

SETTINGS_KEY = "balance_history"
TICK_SECONDS = 60
MIN_GAP = timedelta(minutes=5)  # a change is recorded this soon at the earliest
COMPACT_EVERY_SECONDS = 3600
MAX_ROWS = 5000


class BalanceHistorySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    interval_minutes: int = Field(default=60, ge=5, le=1440)
    detail_days: int = Field(default=14, ge=1, le=365)  # then one a day
    keep_days: int = Field(default=0, ge=0, le=36500)  # 0 = forever


def load_settings(db: DbSession) -> BalanceHistorySettings:
    row = db.get(AppSetting, SETTINGS_KEY)
    return BalanceHistorySettings(**row.value) if row else BalanceHistorySettings()


def save_settings(db: DbSession, s: BalanceHistorySettings, actor: str | None) -> None:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        db.add(AppSetting(key=SETTINGS_KEY, value=s.model_dump(), updated_by=actor))
    else:
        row.value, row.updated_by = s.model_dump(), actor


# ---- recording ---------------------------------------------------------------------------


def signature(db: DbSession) -> tuple:
    """Changes whenever a balance or the set of wallets changes (cheap to read)."""
    return (
        db.scalar(select(func.count()).select_from(Holding)),
        db.scalar(select(func.max(Holding.updated_at))),
        db.scalar(select(func.count()).select_from(Wallet)),
        db.scalar(select(func.max(Wallet.created_at))),
    )


def latest(db: DbSession) -> datetime | None:
    return db.scalar(select(func.max(BalanceSnapshot.at)))


def is_due(db, settings: BalanceHistorySettings, now: datetime, changed: bool) -> bool:
    last = latest(db)
    if last is None:
        return True
    since = now - last
    # 30 s of slack so a tick that's a little early still records.
    return since >= timedelta(minutes=settings.interval_minutes, seconds=-30) or (
        changed and since >= MIN_GAP
    )


def record(db: DbSession, snap, now: datetime) -> int:
    """One snapshot of every wallet (archived too). Returns the number of points written."""
    if snap.stale or not db.scalar(select(func.count()).select_from(Wallet)):
        return 0
    coins = all_coins(db)
    shot = BalanceSnapshot(at=now, daily=False)
    db.add(shot)
    db.flush()
    n = 0
    for h in db.scalars(select(Holding).order_by(Holding.wallet_id, Holding.symbol)):
        amount = Decimal(h.amount)
        coin = coins.get(h.symbol)
        quotes = snap.quotes.get(coin.coingecko_id, {}) if coin else {}
        values = {
            f: round_fiat(value(amount, q, f), f) for f, q in sorted(quotes.items()) if f in FIATS
        }
        db.add(
            BalancePoint(
                snapshot_id=shot.id,
                wallet_id=h.wallet_id,
                symbol=h.symbol,
                amount=h.amount,
                values=values,
            )
        )
        n += 1
    return n


def day_start(at: datetime) -> datetime:
    return at.replace(hour=0, minute=0, second=0, microsecond=0)


def compact(db: DbSession, settings: BalanceHistorySettings, now: datetime) -> dict:
    """Keep one snapshot per day (its last) for whole days older than detail_days; then drop
    days past keep_days."""
    cutoff = day_start(now - timedelta(days=settings.detail_days))
    old = db.execute(
        select(BalanceSnapshot.id, BalanceSnapshot.at, BalanceSnapshot.daily)
        .where(BalanceSnapshot.at < cutoff)
        .order_by(BalanceSnapshot.at)
    ).all()
    by_day: dict[datetime, list] = {}
    for row in old:
        by_day.setdefault(day_start(row.at), []).append(row)
    drop, keep = [], []
    for rows in by_day.values():
        *earlier, last = rows
        drop += [r.id for r in earlier]
        if not last.daily:
            keep.append(last.id)
    if keep:
        db.execute(update(BalanceSnapshot).where(BalanceSnapshot.id.in_(keep)).values(daily=True))
    pruned = 0
    if settings.keep_days:
        too_old = now - timedelta(days=settings.keep_days)
        drop += db.scalars(select(BalanceSnapshot.id).where(BalanceSnapshot.at < too_old)).all()
    drop = sorted(set(drop))
    for i in range(0, len(drop), 500):  # SQLite caps the number of parameters
        chunk = drop[i : i + 500]
        # Points first: don't rely on foreign key cascades for this.
        db.execute(delete(BalancePoint).where(BalancePoint.snapshot_id.in_(chunk)))
        pruned += db.execute(delete(BalanceSnapshot).where(BalanceSnapshot.id.in_(chunk))).rowcount
    return {"snapshots_kept_daily": len(keep), "snapshots_removed": pruned}


class BalanceHistoryJob:
    """Runs in the server (with the price job): records when due, compacts now and then."""

    def __init__(self, service, session_factory):
        self.service = service
        self.factory = session_factory
        self._seen: tuple | None = None  # the balances' signature at the last snapshot
        self._last_compact: float | None = None
        self.last_result: dict = {}

    def tick(self) -> dict:
        result: dict = {"recorded": 0}
        with self.factory() as db:
            settings = load_settings(db)
            if not settings.enabled:
                return {"disabled": True}
            if features.load(db).practice_prices:
                return {"skipped": "practice prices are on"}
            sig = signature(db)
            if not sig[2]:
                return {"skipped": "no wallets"}
            due = is_due(db, settings, utcnow(), sig != self._seen)
        snap = None
        if due:
            try:
                # With no session open: the price source can take 10 s to answer.
                snap = self.service.fresh(self.factory)
            except PricesUnavailable as e:
                result["skipped"] = str(e)
            if snap is not None and snap.stale:
                result["skipped"], snap = "prices are stale", None
        with self.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            now = utcnow()
            if snap is not None:
                sig = signature(db)  # again, under the lock: what's recorded is what's seen
                if is_due(db, settings, now, sig != self._seen):
                    result["recorded"] = record(db, snap, now)
                    self._seen = sig
            if (
                self._last_compact is None
                or time.monotonic() - self._last_compact >= COMPACT_EVERY_SECONDS
            ):
                result.update(compact(db, settings, now))
                self._last_compact = time.monotonic()
            db.commit()
        self.last_result = result
        return result

    async def run_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # one bad tick must never stop the history for good
                log.exception("balance history tick failed")
            await asyncio.sleep(TICK_SECONDS)


# ---- reading -----------------------------------------------------------------------------


def thin(rows: list, most: int) -> list:
    """At most `most` rows, evenly spread, always keeping the first and the last."""
    if len(rows) <= most or most < 2:
        return rows
    step = (len(rows) - 1) / (most - 1)
    return [rows[round(i * step)] for i in range(most)]


def _snapshots(db: DbSession, since: datetime):
    return db.execute(
        select(BalanceSnapshot.id, BalanceSnapshot.at)
        .where(BalanceSnapshot.at >= since)
        .order_by(BalanceSnapshot.at)
        .limit(MAX_ROWS)
    ).all()


def _points(db: DbSession, since: datetime, snap_ids, wallet_ids: list[int]) -> dict[int, list]:
    out: dict[int, list] = {}
    if not wallet_ids:
        return out
    wanted = set(snap_ids)
    rows = db.scalars(
        select(BalancePoint)
        .join(BalanceSnapshot, BalanceSnapshot.id == BalancePoint.snapshot_id)
        .where(BalanceSnapshot.at >= since, BalancePoint.wallet_id.in_(wallet_ids))
    )
    for p in rows:
        if p.snapshot_id in wanted:
            out.setdefault(p.snapshot_id, []).append(p)
    return out


def _total(points, fiat: str) -> tuple[Decimal, list[str]]:
    total, unpriced = Decimal(0), set()
    for p in points:
        v = p.values.get(fiat)
        if v is None:
            if Decimal(p.amount):
                unpriced.add(p.symbol)
        else:
            total = money.add(total, Decimal(v))
    return total, sorted(unpriced)


def wallet_series(db: DbSession, wallet: Wallet, fiat: str, since: datetime) -> list[dict]:
    """The wallet's value (and coins) at each snapshot since it was created, oldest first."""
    snaps = [s for s in _snapshots(db, since) if s.at >= wallet.created_at]
    points = _points(db, since, [s.id for s in snaps], [wallet.id])
    rows = []
    for s in snaps:
        pts = points.get(s.id, [])
        total, unpriced = _total(pts, fiat)
        rows.append(
            {
                "at": s.at,
                "value": round_fiat(total, fiat),
                "unpriced": unpriced,
                "coins": {p.symbol: p.amount for p in sorted(pts, key=lambda p: p.symbol)},
            }
        )
    return rows


def portfolio_series(
    db: DbSession, wallets: list[Wallet], fiat: str, since: datetime
) -> list[dict]:
    """These wallets' combined value at each snapshot, oldest first (a wallet counts from the
    snapshot after it was created)."""
    if not wallets:
        return []
    first = min(w.created_at for w in wallets)
    snaps = [s for s in _snapshots(db, since) if s.at >= first]
    points = _points(db, since, [s.id for s in snaps], [w.id for w in wallets])
    rows = []
    for s in snaps:
        total, unpriced = _total(points.get(s.id, []), fiat)
        rows.append({"at": s.at, "value": round_fiat(total, fiat), "unpriced": unpriced})
    return rows


def change(rows: list[dict], fiat: str) -> dict | None:
    """From the first row to the last: the difference, and in percent (None from zero)."""
    if len(rows) < 2:
        return None
    first, last = Decimal(rows[0]["value"]), Decimal(rows[-1]["value"])
    diff = money.subtract(last, first)
    pct = None if not first else (diff * 100 / first).quantize(Decimal("0.01"))
    return {
        "from": rows[0]["value"],
        "to": rows[-1]["value"],
        "amount": round_fiat(diff, fiat),
        "percent": None if pct is None else str(pct),
    }


def stats(db: DbSession) -> dict:
    return {
        "snapshots": db.scalar(select(func.count()).select_from(BalanceSnapshot)) or 0,
        "points": db.scalar(select(func.count()).select_from(BalancePoint)) or 0,
        "newest": latest(db),
        "oldest": db.scalar(select(func.min(BalanceSnapshot.at))),
    }
