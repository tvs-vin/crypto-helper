"""Price history: detailed points every few minutes, compacted into candles later.

Defaults (all adjustable with prices.manage): a point every 10 minutes kept for 24 hours,
then compacted into hourly open/high/low/close candles kept forever, in USD only.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from app.models import AppSetting, PriceCandle, PricePoint
from app.money import format_amount
from app.prices.catalog import FIATS

SETTINGS_KEY = "price_history"
# Candle sizes that divide a day evenly, so candles line up on clock hours.
COARSE_CHOICES = (15, 20, 30, 60, 120, 180, 240, 360, 480, 720, 1440)
MAX_QUERY_ROWS = 5000

Fiat = Literal["usd", "eur", "gbp", "jpy", "cad", "aud"]


class HistorySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    fine_interval_minutes: int = Field(default=10, ge=1, le=60)
    fine_keep_hours: int = Field(default=24, ge=1, le=720)
    coarse_interval_minutes: int = 60
    coarse_keep_days: int = Field(default=0, ge=0, le=36500)  # 0 = keep forever
    fiats: list[Fiat] = Field(default_factory=lambda: ["usd"], min_length=1, max_length=len(FIATS))

    @field_validator("fiats")
    @classmethod
    def _unique(cls, v):
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def _consistent(self):
        if self.coarse_interval_minutes not in COARSE_CHOICES:
            raise ValueError(f"coarse_interval_minutes must be one of {COARSE_CHOICES}")
        if self.coarse_interval_minutes % self.fine_interval_minutes:
            raise ValueError("coarse_interval_minutes must be a multiple of fine_interval_minutes")
        return self


def load_settings(db: DbSession) -> HistorySettings:
    row = db.get(AppSetting, SETTINGS_KEY)
    return HistorySettings(**row.value) if row else HistorySettings()


def save_settings(db: DbSession, settings: HistorySettings, actor: str | None) -> None:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        db.add(AppSetting(key=SETTINGS_KEY, value=settings.model_dump(), updated_by=actor))
    else:
        row.value = settings.model_dump()
        row.updated_by = actor


def is_due(db: DbSession, settings: HistorySettings, now: datetime) -> bool:
    latest = db.scalar(select(func.max(PricePoint.at)))
    # 30 s of slack so a background tick that's a little early still records.
    return latest is None or now - latest >= timedelta(
        minutes=settings.fine_interval_minutes, seconds=-30
    )


def record(db: DbSession, snap, settings: HistorySettings) -> int:
    """Store one detailed point per coin and fiat. Stale prices are never recorded."""
    if snap.stale:
        return 0
    n = 0
    for cid, by_fiat in snap.quotes.items():
        for fiat in settings.fiats:
            q = by_fiat.get(fiat)
            if q is None:
                continue
            db.add(
                PricePoint(
                    coingecko_id=cid,
                    fiat=fiat,
                    at=snap.as_of,
                    price=format_amount(q.price),
                    change_24h=None if q.change_24h is None else str(q.change_24h),
                )
            )
            n += 1
    return n


def bucket_start(at: datetime, minutes: int) -> datetime:
    midnight = at.replace(hour=0, minute=0, second=0, microsecond=0)
    offset = (at - midnight) // timedelta(minutes=minutes)
    return midnight + offset * timedelta(minutes=minutes)


def compact(db: DbSession, settings: HistorySettings, now: datetime) -> dict:
    """Fold detailed points older than fine_keep_hours into candles, then delete them.

    Only whole candles are made (a candle whose time span ends before the cutoff), so a
    candle never needs merging later. Then candles past coarse_keep_days are deleted.
    """
    cutoff = now - timedelta(hours=settings.fine_keep_hours)
    size = settings.coarse_interval_minutes
    usable_before = bucket_start(cutoff, size)  # buckets starting before this are complete
    points = db.scalars(
        select(PricePoint)
        .where(PricePoint.at < usable_before)
        .order_by(PricePoint.at, PricePoint.id)
    ).all()
    groups: dict[tuple, list[PricePoint]] = {}
    for p in points:
        groups.setdefault((p.coingecko_id, p.fiat, bucket_start(p.at, size)), []).append(p)
    written = 0
    for (cid, fiat, start), pts in groups.items():
        prices = [Decimal(p.price) for p in pts]
        existing = db.scalar(
            select(PriceCandle).where(
                PriceCandle.coingecko_id == cid,
                PriceCandle.fiat == fiat,
                PriceCandle.interval_minutes == size,
                PriceCandle.start == start,
            )
        )
        if existing:  # only if settings changed mid-way; merge rather than lose data
            prices = [
                Decimal(existing.open),
                *prices,
                Decimal(existing.low),
                Decimal(existing.high),
            ]
            existing.high = format_amount(max(prices))
            existing.low = format_amount(min(prices))
            existing.close = pts[-1].price
            existing.points += len(pts)
        else:
            db.add(
                PriceCandle(
                    coingecko_id=cid,
                    fiat=fiat,
                    interval_minutes=size,
                    start=start,
                    open=pts[0].price,
                    high=format_amount(max(prices)),
                    low=format_amount(min(prices)),
                    close=pts[-1].price,
                    points=len(pts),
                )
            )
            written += 1
    deleted = 0
    if points:
        deleted = db.execute(
            delete(PricePoint).where(PricePoint.id.in_([p.id for p in points]))
        ).rowcount
    pruned = 0
    if settings.coarse_keep_days:
        pruned = db.execute(
            delete(PriceCandle).where(
                PriceCandle.start < now - timedelta(days=settings.coarse_keep_days)
            )
        ).rowcount
    return {"candles_written": written, "points_compacted": deleted, "candles_pruned": pruned}


def query(db: DbSession, coingecko_id: str, fiat: str, since: datetime) -> list[dict]:
    """Candles for the older part, detailed points for the recent part, oldest first."""
    candles = db.scalars(
        select(PriceCandle)
        .where(
            PriceCandle.coingecko_id == coingecko_id,
            PriceCandle.fiat == fiat,
            PriceCandle.start >= since,
        )
        .order_by(PriceCandle.start)
        .limit(MAX_QUERY_ROWS)
    ).all()
    points = db.scalars(
        select(PricePoint)
        .where(
            PricePoint.coingecko_id == coingecko_id, PricePoint.fiat == fiat, PricePoint.at >= since
        )
        .order_by(PricePoint.at)
        .limit(MAX_QUERY_ROWS)
    ).all()
    rows = [
        {
            "at": c.start,
            "price": c.close,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "kind": "candle",
            "interval_minutes": c.interval_minutes,
            "points": c.points,
        }
        for c in candles
    ]
    rows += [
        {"at": p.at, "price": p.price, "kind": "point", "change_24h": p.change_24h} for p in points
    ]
    rows.sort(key=lambda r: r["at"])
    return rows[-MAX_QUERY_ROWS:]


def stats(db: DbSession) -> dict:
    return {
        "points": db.scalar(select(func.count()).select_from(PricePoint)) or 0,
        "candles": db.scalar(select(func.count()).select_from(PriceCandle)) or 0,
        "newest_point": db.scalar(select(func.max(PricePoint.at))),
        "oldest_candle": db.scalar(select(func.min(PriceCandle.start))),
    }
