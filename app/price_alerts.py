"""Price alerts (milestone 9d): the first part of the track-and-alert bot job.

Each person sets their own: a coin goes above or below a price, or moves more than N % in 24
hours, in one currency. A background job looks whenever the prices are fetched again. An alert
fires once and then waits until the price has crossed back (by a small margin, so a price
hovering at the line can't flood anyone) before it can fire again.

Never on made-up numbers: nothing is checked while practice prices are on, or while the prices
are stale (the source failed and old ones are being shown).
"""

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import features
from app import notifications as nt
from app.deps import effective_permissions
from app.models import PriceAlert, User
from app.prices.service import PricesUnavailable
from app.prices.valuation import round_fiat
from app.timeutil import utcnow

log = logging.getLogger(__name__)

KINDS = ("above", "below", "move")
MAX_PER_USER = 50
MOVE_MIN, MOVE_MAX = Decimal("0.1"), Decimal("1000")
REARM_MARGIN = Decimal("0.005")  # above/below: back across the line by 0.5 %
MOVE_REARM = Decimal("0.8")  # move: back under 80 % of the threshold
TICK_SECONDS = 60


def met(kind: str, value: Decimal, price: Decimal | None, change: Decimal | None) -> bool:
    if kind == "above":
        return price is not None and price >= value
    if kind == "below":
        return price is not None and price <= value
    return change is not None and abs(change) >= value


def crossed_back(kind: str, value: Decimal, price: Decimal | None, change) -> bool:
    if kind == "above":
        return price is not None and price < value * (1 - REARM_MARGIN)
    if kind == "below":
        return price is not None and price > value * (1 + REARM_MARGIN)
    return change is not None and abs(change) < value * MOVE_REARM


def fiat_text(value: Decimal, fiat: str) -> str:
    return f"{Decimal(round_fiat(value, fiat)):,} {fiat.upper()}"


def plain(value: Decimal) -> str:
    """A threshold as the person typed it, with thousands separators: 70,000 or 0.5."""
    return f"{value.normalize():,f}"


def describe(a: PriceAlert) -> str:
    v = Decimal(a.value)
    if a.kind == "move":
        return f"{a.symbol} moves {plain(v)} % or more in 24 hours"
    return f"{a.symbol} goes {a.kind} {plain(v)} {a.fiat.upper()}"


def message(a: PriceAlert, price: Decimal | None, change: Decimal | None) -> tuple[str, str]:
    v = Decimal(a.value)
    now = fiat_text(price, a.fiat) if price is not None else "unknown"
    moved = f" ({change:+.1f} % in 24 h)" if change is not None else ""
    if a.kind == "move":
        return (
            f"{a.symbol} moved {change:+.1f} % in 24 hours",
            f"Now {now}. Your alert: a move of {plain(v)} % or more. It can fire again once the "
            "move is smaller.",
        )
    back = v * (1 - REARM_MARGIN) if a.kind == "above" else v * (1 + REARM_MARGIN)
    return (
        f"{a.symbol} is {a.kind} {plain(v)} {a.fiat.upper()}",
        f"Now {now}{moved}. It can fire again once {a.symbol} is back "
        f"{'below' if a.kind == 'above' else 'above'} {fiat_text(back, a.fiat)}.",
    )


def quote(snap, a: PriceAlert):
    q = snap.quotes.get(a.coingecko_id, {}).get(a.fiat)
    return (q.price, q.change_24h) if q is not None else (None, None)


def evaluate(db: DbSession, hub, snap, fired_for: set | None = None) -> list[str]:
    """Check every alert against `snap` (in the caller's write transaction). Returns the titles
    of the ones that fired."""
    alerts = db.scalars(select(PriceAlert).order_by(PriceAlert.id)).all()
    if not alerts:
        return []
    users = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_({a.user_id for a in alerts})))
    }
    fired = []
    for a in alerts:
        price, change = quote(snap, a)
        value = Decimal(a.value)
        if a.armed and met(a.kind, value, price, change):
            a.armed, a.last_fired_at = False, utcnow()
            user = users.get(a.user_id)
            # Only for people who can still see prices (a fired alert stays fired either way).
            if user is not None and "prices.view" in effective_permissions(user):
                title, body = message(a, price, change)
                nt.notify(db, hub, [user], category="prices", title=title, body=body,
                          link="overview")  # fmt: skip
                fired.append(title)
                if fired_for is not None:
                    fired_for.add(user.id)
        elif not a.armed and crossed_back(a.kind, value, price, change):
            a.armed = True
    return fired


def count(db: DbSession, user_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(PriceAlert)
    if user_id is not None:
        stmt = stmt.where(PriceAlert.user_id == user_id)
    return db.scalar(stmt) or 0


class PriceAlertJob:
    def __init__(self, prices, session_factory, hub=None):
        self.prices = prices
        self.factory = session_factory
        self.hub = hub
        self._last_as_of = None

    def tick(self) -> dict:
        from app.db import IMMEDIATE

        with self.factory() as db:
            if not count(db):
                return {"alerts": 0}
            if features.load(db).practice_prices:
                return {"skipped": "practice prices are on"}
        try:
            snap = self.prices.fresh(self.factory)  # no database session open meanwhile
        except PricesUnavailable as e:
            return {"skipped": str(e)}
        if snap.stale or self.prices.practice:
            return {"skipped": "prices are stale" if snap.stale else "practice prices are on"}
        if snap.as_of == self._last_as_of:
            return {"skipped": "no new prices yet"}
        whose: set[int] = set()
        with self.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            fired = evaluate(db, self.hub, snap, whose)
            db.commit()
        if whose:
            from app import live

            live.publish(self.hub, self.factory, ["alerts"], only=whose)
        self._last_as_of = snap.as_of
        if fired:
            log.info("price alerts fired: %s", "; ".join(fired))
        return {"fired": fired}

    async def run_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # one bad pass must never stop the alerts for good
                log.exception("price alert check failed")
            await asyncio.sleep(TICK_SECONDS)
