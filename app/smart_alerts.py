"""Smarter alerts (12a), next to the price alerts of 9d. Four kinds, each person's own:

- portfolio: your wallets' total above or below an amount, or moving X % over 24 hours or 7 days
  (the past value comes from balance history);
- wallet: a synced wallet's balance changed (a deposit, a withdrawal, a reward): raised by the
  sync engine as it applies the change, optionally only above a value;
- drift: your coins' shares of the portfolio are off your target percentages by more than N
  points (the same targets the rebalancing strategy will use);
- trend: a coin crosses its N-day moving average, or falls X % from its N-day high (daily prices
  from app/prices/daily.py, plus the live price).

Like price alerts, an alert fires once and re-arms only when things are back on the other side;
a moving-average cross fires each time the price changes sides. Nothing is checked on stale or
practice prices. Anything that reveals holdings is marked with notifications.detail(), so Discord
only gets it if the person allows it.
"""

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import features
from app import notifications as nt
from app.deps import effective_permissions
from app.models import Alert, User, Wallet
from app.prices import daily
from app.prices.catalog import FIATS, all_coins
from app.prices.service import PricesUnavailable
from app.prices.valuation import portfolio, round_fiat
from app.timeutil import utcnow

log = logging.getLogger(__name__)

KINDS = ("portfolio", "wallet", "drift", "trend")
MAX_PER_USER = 50
REARM_MARGIN = Decimal("0.005")  # above/below: back across the line by 0.5 %
MOVE_REARM = Decimal("0.8")  # moves and drops: back under 80 % of the threshold
TICK_SECONDS = 60
Fiat = Literal["usd", "eur", "gbp", "jpy", "cad", "aud"]


def _number(v, low: Decimal, high: Decimal, what: str) -> str:
    try:
        d = Decimal(str(v).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{what} must be a number") from None
    if not d.is_finite() or not low <= d <= high:
        raise ValueError(f"{what} must be between {low.normalize():f} and {high.normalize():f}")
    return format(d.normalize(), "f")


class PortfolioParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition: Literal["above", "below", "move"]
    value: str = Field(max_length=40)  # an amount in `fiat`, or a percent for "move"
    fiat: Fiat = "usd"
    window: Literal["24h", "7d"] = "24h"

    @model_validator(mode="after")
    def _value(self):
        if self.condition == "move":
            self.value = _number(self.value, Decimal("0.1"), Decimal(1000), "The percent")
        else:
            self.value = _number(self.value, Decimal("0.01"), Decimal("1e15"), "The amount")
        return self


class WalletParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wallet_id: int | None = None  # None: any synced wallet
    direction: Literal["any", "up", "down"] = "any"
    min_value: str | None = Field(default=None, max_length=40)
    fiat: Fiat = "usd"

    @field_validator("min_value")
    @classmethod
    def _min(cls, v):
        return None if v in (None, "") else _number(v, Decimal(0), Decimal("1e15"), "The minimum")


class DriftParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: dict[str, str] = Field(min_length=1, max_length=20)  # symbol -> percent
    threshold: str = Field(max_length=10)  # percentage points

    @model_validator(mode="after")
    def _check(self):
        clean = {}
        for sym, pct in self.targets.items():
            s = sym.strip().upper()
            if not s.isalnum() or len(s) > 10:
                raise ValueError(f"{sym!r} isn't a coin symbol")
            clean[s] = _number(pct, Decimal("0.1"), Decimal(100), f"{s}'s target")
        if sum(Decimal(v) for v in clean.values()) > 100:
            raise ValueError("The targets add up to more than 100 %")
        self.targets = clean
        self.threshold = _number(self.threshold, Decimal(1), Decimal(50), "The threshold")
        return self


class TrendParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=16)
    signal: Literal["ma_cross", "drawdown"]
    days: int = Field(ge=5, le=365)
    direction: Literal["up", "down", "either"] = "either"  # ma_cross
    percent: str | None = Field(default=None, max_length=10)  # drawdown

    @model_validator(mode="after")
    def _check(self):
        self.symbol = self.symbol.strip().upper()
        if self.signal == "drawdown":
            if self.percent is None:
                raise ValueError("A drop needs a percent")
            self.percent = _number(self.percent, Decimal(1), Decimal(90), "The drop")
        else:
            self.percent = None
        return self


PARAMS = {
    "portfolio": PortfolioParams,
    "wallet": WalletParams,
    "drift": DriftParams,
    "trend": TrendParams,
}
# What each kind needs, on top of having the alert at all.
NEEDS = {
    "portfolio": {"wallets.view", "prices.view"},
    "wallet": {"wallets.view"},
    "drift": {"wallets.view", "prices.view"},
    "trend": {"prices.view"},
}
CATEGORY = {
    "portfolio": "portfolio",
    "wallet": "portfolio",
    "drift": "portfolio",
    "trend": "prices",
}


def allowed(user: User, kind: str) -> bool:
    return NEEDS[kind] <= effective_permissions(user)


def plain(v) -> str:
    return f"{Decimal(v).normalize():,f}"


def money_text(v: Decimal, fiat: str) -> str:
    return f"{Decimal(round_fiat(v, fiat)):,} {fiat.upper()}"


def describe(a: Alert, wallet_names: dict[int, str] | None = None) -> str:
    p = a.params
    if a.kind == "portfolio":
        if p["condition"] == "move":
            window = "24 hours" if p.get("window", "24h") == "24h" else "7 days"
            return f"Portfolio moves {plain(p['value'])} % or more in {window}"
        return f"Portfolio goes {p['condition']} {plain(p['value'])} {p['fiat'].upper()}"
    if a.kind == "wallet":
        name = (wallet_names or {}).get(p.get("wallet_id")) or "Any synced wallet"
        which = {"any": "changes", "up": "goes up", "down": "goes down"}[p.get("direction", "any")]
        more = (
            f" by {plain(p['min_value'])} {p['fiat'].upper()} or more" if p.get("min_value") else ""
        )
        return f"{name}: a balance {which}{more}"
    if a.kind == "drift":
        split = ", ".join(f"{s} {plain(v)} %" for s, v in p["targets"].items())
        return f"Drift of more than {plain(p['threshold'])} points from {split}"
    if p["signal"] == "ma_cross":
        way = {"up": " above", "down": " below", "either": ""}[p.get("direction", "either")]
        return f"{p['symbol']} crosses{way} its {p['days']}-day average"
    return f"{p['symbol']} falls {plain(p['percent'])} % from its {p['days']}-day high"


# ---- checking ------------------------------------------------------------------------------


def _fire(db, hub, user, a: Alert, title: str, body: str) -> str:
    a.last_fired_at = utcnow()
    nt.notify(db, hub, [user], category=CATEGORY[a.kind], title=title, body=body, link="alerts")
    return nt.render(title)


def _portfolio(db, hub, user, a: Alert, snap, coins) -> str | None:
    p = a.params
    fiat = p["fiat"]
    total = Decimal(portfolio(db, snap, coins, fiat, include_archived=False)["total"])
    v = Decimal(p["value"])
    if p["condition"] in ("above", "below"):
        met = total >= v if p["condition"] == "above" else total <= v
        back = (
            total < v * (1 - REARM_MARGIN)
            if p["condition"] == "above"
            else total > v * (1 + REARM_MARGIN)
        )
        if a.armed and met:
            a.armed = False
            level = nt.detail("values", money_text(v, fiat), "your alert's level")
            now = nt.detail("values", money_text(total, fiat), "past it")
            return _fire(
                db, hub, user, a, f"Your portfolio is {p['condition']} {level}", f"Now {now}."
            )
        if not a.armed and back:
            a.armed = True
        return None
    from app import balance_history as bh

    hours = 24 if p.get("window", "24h") == "24h" else 168
    then = utcnow() - timedelta(hours=hours)
    wallets = db.scalars(select(Wallet).where(Wallet.archived.is_(False))).all()
    rows = [
        r
        for r in bh.portfolio_series(db, wallets, fiat, then - timedelta(days=1))
        if r["at"] <= then
    ]
    if not rows or not Decimal(rows[-1]["value"]):
        a.state = {**a.state, "note": "not enough balance history yet"}
        return None
    past = Decimal(rows[-1]["value"])
    pct = (total - past) * 100 / past
    if a.armed and abs(pct) >= v:
        a.armed = False
        window = "24 hours" if hours == 24 else "7 days"
        return _fire(
            db, hub, user, a,
            f"Your portfolio moved {pct:+.1f} % in {window}",
            "From " + nt.detail("values", money_text(past, fiat), "its earlier value")
            + " to " + nt.detail("values", money_text(total, fiat), "now") + ".",
        )  # fmt: skip
    if not a.armed and abs(pct) < v * MOVE_REARM:
        a.armed = True
    return None


def shares(db, snap, coins) -> dict[str, Decimal] | None:
    """Each coin's percent of the portfolio (USD values), or None if it's empty."""
    folio = portfolio(db, snap, coins, "usd", include_archived=False)
    values = {c["symbol"]: Decimal(c["value"]) for c in folio["coins"] if c["value"] is not None}
    total = sum(values.values(), Decimal(0))
    if not total:
        return None
    return {s: v * 100 / total for s, v in values.items()}


def _drift(db, hub, user, a: Alert, snap, coins) -> str | None:
    p = a.params
    pct = shares(db, snap, coins)
    if pct is None:
        return None
    targets = {s: Decimal(v) for s, v in p["targets"].items()}
    rest = 100 - sum(targets.values())
    actual = {s: pct.get(s, Decimal(0)) for s in targets}
    other = sum((v for s, v in pct.items() if s not in targets), Decimal(0))
    th = Decimal(p["threshold"])
    off = [(s, actual[s], targets[s]) for s in targets if abs(actual[s] - targets[s]) > th]
    if rest > 0 and abs(other - rest) > th:
        off.append(("other coins", other, rest))
    if a.armed and off:
        a.armed = False
        parts = [
            f"{s} " + nt.detail("allocation", f"{now:.1f} % (target {plain(t)} %)",
                                "is above its target" if now > t else "is below its target")
            for s, now, t in off
        ]  # fmt: skip
        return _fire(
            db,
            hub,
            user,
            a,
            "Your portfolio drifted from its targets",
            "; ".join(parts) + ". Rebalancing would bring it back.",
        )
    if not a.armed and not off:
        a.armed = True
    return None


def _trend(db, hub, user, a: Alert, snap, coins) -> str | None:
    p = a.params
    coin = coins.get(p["symbol"])
    q = snap.quotes.get(coin.coingecko_id, {}).get("usd") if coin else None
    if q is None:
        return None
    price = q.price
    today = utcnow().date()
    days = [c for c in daily.recent(db, p["symbol"], p["days"] + 1) if c.day < today][-p["days"] :]
    if len(days) < p["days"]:
        a.state = {**a.state, "note": f"needs {p['days']} days of daily prices"}
        return None
    sym, n = p["symbol"], p["days"]
    if p["signal"] == "ma_cross":
        ma = daily.moving_average([Decimal(c.close) for c in days])
        side = "above" if price >= ma else "below"
        before = a.state.get("side")
        a.state = {"side": side, "ma": format(ma.quantize(Decimal("0.01")), "f")}
        wanted = p.get("direction", "either")
        if before and before != side and wanted in ("either", "up" if side == "above" else "down"):
            return _fire(
                db,
                hub,
                user,
                a,
                f"{sym} crossed {side} its {n}-day average",
                f"Now {money_text(price, 'usd')}; the {n}-day average is {money_text(ma, 'usd')}.",
            )
        return None
    high = max([Decimal(c.high) for c in days] + [price])
    drop = (high - price) * 100 / high
    pct = Decimal(p["percent"])
    a.state = {"drop": format(drop.quantize(Decimal("0.1")), "f")}
    if a.armed and drop >= pct:
        a.armed = False
        return _fire(
            db,
            hub,
            user,
            a,
            f"{sym} is {drop:.1f} % below its {n}-day high",
            f"Now {money_text(price, 'usd')}; the high was {money_text(high, 'usd')}. It can fire "
            "again once the drop is smaller.",
        )
    if not a.armed and drop < pct * MOVE_REARM:
        a.armed = True
    return None


CHECKS = {"portfolio": _portfolio, "drift": _drift, "trend": _trend}


def evaluate(db: DbSession, hub, snap, fired_for: set | None = None) -> list[str]:
    """Check every portfolio, drift and trend alert (in the caller's write transaction).
    `fired_for` collects whose alerts fired (their Alerts windows are told)."""
    alerts = db.scalars(select(Alert).where(Alert.kind.in_(CHECKS)).order_by(Alert.id)).all()
    if not alerts:
        return []
    users = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_({a.user_id for a in alerts})))
    }
    coins = all_coins(db)
    fired = []
    for a in alerts:
        user = users.get(a.user_id)
        if user is None or not user.is_active or not allowed(user, a.kind):
            continue  # it waits; nothing is told to someone who can't see it any more
        title = CHECKS[a.kind](db, hub, user, a, snap, coins)
        if title:
            fired.append(title)
            if fired_for is not None:
                fired_for.add(user.id)
    return fired


def wallet_changed(db: DbSession, hub, wallet: Wallet, diffs, snap) -> int:
    """The sync engine changed a synced wallet's balances: tell whoever asked. `diffs` are
    (symbol, old, new) amounts; `snap` the last prices (may be None: then a minimum value can't
    be checked, and such alerts wait for the next change)."""
    if not diffs:
        return 0
    alerts = db.scalars(select(Alert).where(Alert.kind == "wallet")).all()
    coins = all_coins(db)
    told = 0
    for a in alerts:
        p = a.params
        if p.get("wallet_id") not in (None, wallet.id):
            continue
        user = db.get(User, a.user_id)
        if user is None or not user.is_active or not allowed(user, "wallet"):
            continue
        lines = []
        for symbol, old, new in diffs:
            up = new > old
            if p.get("direction", "any") == ("down" if up else "up"):
                continue
            change = abs(new - old)
            value = None
            coin = coins.get(symbol)
            q = snap.quotes.get(coin.coingecko_id, {}).get(p["fiat"]) if snap and coin else None
            if q is not None:
                value = change * q.price
            if p.get("min_value") and (value is None or value < Decimal(p["min_value"])):
                continue
            worth = ""
            if value is not None:
                worth = nt.detail("values", f" (about {money_text(value, p['fiat'])})")
            by = nt.detail("amounts", f" by {plain(change)} {symbol}")
            lines.append(f"{symbol} went {'up' if up else 'down'}{by}{worth}")
        if not lines:
            continue
        name = wallet.nickname or wallet.name
        down = any(new < old for _, old, new in diffs)
        _fire(
            db, hub, user, a,
            nt.detail("wallets", name, "A synced wallet") + ": balance changed",
            ". ".join(lines) + "."
            + (" If you didn't expect this, check the account now." if down else ""),
        )  # fmt: skip
        told += 1
    return told


def count(db: DbSession, user_id: int | None = None, kinds=KINDS) -> int:
    stmt = select(func.count()).select_from(Alert).where(Alert.kind.in_(kinds))
    if user_id is not None:
        stmt = stmt.where(Alert.user_id == user_id)
    return db.scalar(stmt) or 0


class SmartAlertJob:
    def __init__(self, prices, session_factory, hub=None):
        self.prices = prices
        self.factory = session_factory
        self.hub = hub
        self._last_as_of = None

    def tick(self) -> dict:
        from app.db import IMMEDIATE

        with self.factory() as db:
            if not count(db, kinds=tuple(CHECKS)):
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
            log.info("alerts fired: %s", "; ".join(fired))
        return {"fired": fired}

    async def run_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # one bad pass must never stop the alerts for good
                log.exception("alert check failed")
            await asyncio.sleep(TICK_SECONDS)


FIAT_CHOICES = tuple(FIATS)
