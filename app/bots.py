"""Paper trading (12d): the backtester's plans, run live with made-up money.

A bot is one plan with its own paper account (cash, coins, what they cost), separate from
wallets, so practice money never mixes with your portfolio, its history or its alerts.

How a bot trades (the backtester's rules, live):
- Once a day, after a UTC day has closed and its daily prices are in, the bot decides on that
  close, with the same code as the backtester (`backtest.decide`), adding any scheduled money
  first. The orders wait.
- Waiting orders are filled at the next check (every minute) at the **live** price, with the
  bot's slippage and fee, within its limits. A buy-and-hold twin gets the same money at the
  same moments, so the comparison is fair.
- Nothing is filled on practice prices or stale ones; if prices stay stale for 15 minutes while
  bots wait, the kill switch trips.

Risk limits (each bot): the largest order and the most spent in a day (orders are cut down to
fit); a held coin falling more than N % below what the bot paid for it pauses the bot; the bot
losing more than N % of its value in a day trips the kill switch.

The kill switch stops every bot at once: waiting orders are cancelled, bots are paused, and it
stays tripped until a person re-arms it (`bots.run`); bots then have to be started again one by
one. Tripping and re-arming are always audited.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import backtest as bt
from app import features, money
from app import notifications as nt
from app.audit import record
from app.deps import effective_permissions
from app.models import AppSetting, Bot, BotOrder, BotPoint, DailyCandle, User
from app.prices.catalog import all_coins
from app.prices.service import PricesUnavailable
from app.prices.valuation import round_fiat
from app.timeutil import utcnow

log = logging.getLogger(__name__)

KILL_KEY = "kill_switch"
STALE_TRIP = timedelta(minutes=15)
TICK_SECONDS = 60
POINT_EVERY = timedelta(hours=1)
MAX_BOTS = 20
ACTOR = "<bots>"
UNITS = Decimal("1e-8")
MAX_GAP = timedelta(hours=6)  # the bot check stopped this long: the clean run starts again
DRILLS_KEY = "kill_drills"


class BotParams(BaseModel):
    """A bot's plan: the backtester's settings without the dates."""

    model_config = ConfigDict(extra="forbid")
    strategy: str
    coins: dict[str, str]
    currency: str = "usd"
    initial: str = "1000"
    contribution: str = "0"
    every: str = "none"
    fee_pct: str = "0.9"
    slippage_pct: str = "0.1"
    rebalance: str = "quarter"
    band: str = "5"
    dip_pct: str = "20"
    dip_days: int = 30
    dip_amount: str = "100"
    ma_days: int = 50

    @model_validator(mode="after")
    def _check(self):
        # The backtester's own rules (dates are just placeholders to satisfy them).
        p = bt.Params(**self.model_dump(), start=date(2000, 1, 1), end=date(2000, 2, 1))
        for k in self.model_fields:
            setattr(self, k, getattr(p, k))
        return self


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_order: str | None = None  # in the bot's currency; None: no limit
    max_daily_spend: str | None = None
    position_loss_pct: str | None = "30"  # a held coin this far below its cost: pause
    daily_loss_pct: str | None = "15"  # the bot this much down in a day: kill switch

    @model_validator(mode="after")
    def _check(self):
        for k, low, high in (
            ("max_order", "0.01", "1e12"),
            ("max_daily_spend", "0.01", "1e12"),
            ("position_loss_pct", "1", "99"),
            ("daily_loss_pct", "1", "99"),
        ):
            v = getattr(self, k)
            if v not in (None, ""):
                setattr(self, k, bt._dec(v, Decimal(low), Decimal(high), k.replace("_", " ")))
            else:
                setattr(self, k, None)
        return self


def validate(params: dict, limits: dict) -> tuple[dict, dict]:
    """Normalised (params, limits), or ValueError with the reason."""
    try:
        p = BotParams(**params).model_dump()
        lim = Limits(**limits).model_dump()
    except ValidationError as e:
        raise ValueError(
            "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors())
        ) from None
    return p, lim


# ---- the kill switch -----------------------------------------------------------------------


def kill_state(db: DbSession) -> dict:
    row = db.get(AppSetting, KILL_KEY)
    return {"tripped": False, **(row.value if row else {})}


def _set_kill(db: DbSession, value: dict, by: str) -> None:
    row = db.get(AppSetting, KILL_KEY)
    if row is None:
        db.add(AppSetting(key=KILL_KEY, value=value, updated_by=by))
    else:
        row.value, row.updated_by = value, by


def watchers(db: DbSession) -> list[User]:
    """Who hears about the kill switch: everyone who can see bots."""
    return [
        u
        for u in db.scalars(select(User).where(User.is_active.is_(True)))
        if "bots.view" in effective_permissions(u)
    ]


def trip(
    db: DbSession, hub, by: str, reason: str, user_id: int | None = None, drill: bool = False
) -> bool:
    """Stop every bot: cancel waiting orders, pause running bots. False if already tripped.
    A drill does the same for real; its bots keep their clean run (see app/readiness.py)."""
    if kill_state(db)["tripped"]:
        return False
    now = utcnow()
    cancelled = 0
    for o in db.scalars(select(BotOrder).where(BotOrder.status == "pending")):
        o.status, o.note = "cancelled", "kill switch drill" if drill else "kill switch"
        cancelled += 1
    stopped = live_stopped = 0
    on_their_way = db.scalar(
        select(func.count()).select_from(BotOrder).where(BotOrder.status == "sending")
    )
    for b in db.scalars(select(Bot).where(Bot.status == "running")):
        live_stopped += b.mode == "live"
        b.status = "paused"
        prefix = "kill switch drill" if drill else "kill switch"
        b.status_reason = f"{prefix}: {reason}"[:200]
        b.state = {**(b.state or {}), "paused_by": "drill" if drill else "kill"}
        stopped += 1
    db.flush()
    value = {
        "tripped": True,
        "at": now.isoformat(timespec="seconds"),
        "by": by,
        "reason": reason[:200],
    }
    if drill:  # what the drill proved, checked in the same transaction
        still_running = db.scalar(
            select(func.count()).select_from(Bot).where(Bot.status == "running")
        )
        still_waiting = db.scalar(
            select(func.count()).select_from(BotOrder).where(BotOrder.status == "pending")
        )
        value["drill"] = {
            "bots_stopped": stopped,
            "live_stopped": live_stopped,  # real-money bots among them
            "orders_on_their_way": on_their_way,  # finish by themselves (immediate-or-cancel)
            "orders_cancelled": cancelled,
            "all_stopped": still_running == 0 and still_waiting == 0,
        }
    _set_kill(db, value, by)
    detail = f"{'drill: ' if drill else ''}{reason} ({stopped} stopped)"
    record(db, "bots.kill", user_id=user_id, username=by, detail=detail)
    nt.notify(
        db,
        hub,
        watchers(db),
        category="trading",
        level="warning" if drill else "critical",
        title="Kill switch drill: every bot stopped"
        if drill
        else "Kill switch tripped: every bot stopped",
        body=f"{reason}. {stopped} bot(s) paused; re-arm it in Bots when ready."
        + (" Re-arming completes the drill." if drill else ""),
        link="bots",
    )
    return True


def drill_checked(db: DbSession, job_answer: dict) -> None:
    """After a drill is committed: record that the bot check refused to trade."""
    k = kill_state(db)
    if k.get("drill") is not None:
        refused = job_answer.get("skipped") == "the kill switch is tripped"
        _set_kill(db, {**k, "drill": {**k["drill"], "check_refused": refused}}, k["by"])


def drills(db: DbSession) -> list[dict]:
    row = db.get(AppSetting, DRILLS_KEY)
    return list(row.value.get("drills", [])) if row else []


def rearm(db: DbSession, hub, by: str, user_id: int | None = None) -> bool:
    k = kill_state(db)
    if not k["tripped"]:
        return False
    _set_kill(
        db,
        {
            "tripped": False,
            "rearmed_at": utcnow().isoformat(timespec="seconds"),
            "rearmed_by": by,
            "last": {k2: k[k2] for k2 in ("at", "by", "reason") if k2 in k},
        },
        by,
    )
    if k.get("drill") is not None:  # the drill is complete: keep it (the last 20)
        done = {
            **{k2: k[k2] for k2 in ("at", "by", "reason")},
            **k["drill"],
            "rearmed_at": utcnow().isoformat(timespec="seconds"),
            "rearmed_by": by,
        }
        row = db.get(AppSetting, DRILLS_KEY)
        value = {"drills": ([done] + drills(db))[:20]}
        if row is None:
            db.add(AppSetting(key=DRILLS_KEY, value=value, updated_by=by))
        else:
            row.value, row.updated_by = value, by
    record(db, "bots.rearm", user_id=user_id, username=by, detail=f"after: {k.get('reason')}")
    nt.notify(
        db,
        hub,
        watchers(db),
        category="trading",
        title="Kill switch re-armed",
        body=f"By {by}. Bots stay paused until each is started again.",
        link="bots",
    )
    return True


# ---- the paper account ---------------------------------------------------------------------


def _d(v) -> Decimal:
    return Decimal(str(v or "0"))


def new_account() -> dict:
    return {
        "cash": "0",
        "units": {},
        "cost": {},
        "realized": "0",
        "fees": "0",
        "slippage": "0",
        "put_in": "0",
        "bench_cash": "0",
        "bench_units": {},
        "bench_pending": "0",
    }


def weights(p: dict) -> dict[str, Decimal]:
    return {s: Decimal(v) / 100 for s, v in p["coins"].items()}


def value_of(account: dict, prices: dict[str, Decimal], bench: bool = False) -> Decimal:
    units = account["bench_units" if bench else "units"]
    cash = _d(account["bench_cash" if bench else "cash"])
    with localcontext() as ctx:
        ctx.prec = money.PRECISION
        return cash + sum((_d(u) * prices[s] for s, u in units.items() if s in prices), Decimal(0))


def live_prices(snap, coins, symbols, currency: str) -> dict[str, Decimal] | None:
    out = {}
    for s in symbols:
        c = coins.get(s)
        q = snap.quotes.get(c.coingecko_id, {}).get(currency) if c else None
        if q is None:
            return None
        out[s] = q.price
    return out


def _history(db: DbSession, p: dict, until: date, days: int) -> list[bt.Day]:
    """The last `days` (or more) finished days up to `until`, every coin priced."""
    rows: dict[str, dict[date, DailyCandle]] = {}
    first = until - timedelta(days=days * 2 + 10)
    for s in p["coins"]:
        rows[s] = {
            c.day: c
            for c in db.scalars(
                select(DailyCandle).where(
                    DailyCandle.symbol == s,
                    DailyCandle.quote == p["currency"],
                    DailyCandle.day >= first,
                    DailyCandle.day <= until,
                )
            )
        }
    common = sorted(set.intersection(*(set(r) for r in rows.values()))) if rows else []

    def at(d, k):
        return {s: Decimal(getattr(rows[s][d], k)) for s in p["coins"]}

    return [bt.Day(d, at(d, "open"), at(d, "close"), at(d, "high")) for d in common]


def due_flows(p: dict, start: date, after: date | None, upto: date) -> list[date]:
    """Scheduled money between `after` (exclusive) and `upto` (inclusive), from `start`."""
    if p["every"] == "none" or not Decimal(p["contribution"]):
        return []
    out, d = [], (after or start) + timedelta(days=1)
    while d <= upto:
        if p["every"] == "week" and (d - start).days % 7 == 0:
            out.append(d)
        elif p["every"] == "month" and d.day == min(start.day, _last_day(d)) and d != start:
            out.append(d)
        d += timedelta(days=1)
    return out


def _last_day(d: date) -> int:
    import calendar

    return calendar.monthrange(d.year, d.month)[1]


def decide(db: DbSession, bot: Bot, day: date, first: bool) -> list[BotOrder]:
    """The bot's decision on `day`'s close (money due by then added first). Returns new orders
    (or [] if the day's prices aren't in yet: the bot waits)."""
    p = BotParams(**bot.params)
    need = bt.warmup(p) or 1
    history = _history(db, bot.params, day, need)
    if not history or history[-1].day != day or len(history) < need:
        return []
    acct = dict(bot.account)  # a copy: changing the stored dict in place would never be saved
    st = dict(bot.state)
    start = date.fromisoformat(st["start_day"])
    flow = _d(p.initial) if first else Decimal(0)
    through = date.fromisoformat(st["flows_through"]) if st.get("flows_through") else None
    flow += _d(p.contribution) * len(due_flows(bot.params, start, through, day))
    if bot.mode == "live" and flow > 0:  # real money: never more than the owner's cap
        from app.live_bots import flow_room

        room = flow_room(db, bot)
        if flow > room:
            st["cap_cut"] = {"day": day.isoformat(), "wanted": str(flow), "given": str(room)}
            flow = room
    if flow:
        acct["cash"] = str(_d(acct["cash"]) + flow)
        acct["bench_cash"] = str(_d(acct["bench_cash"]) + flow)
        acct["bench_pending"] = str(_d(acct["bench_pending"]) + flow)
        acct["put_in"] = str(_d(acct["put_in"]) + flow)
    book = bt.Book(
        cash=_d(acct["cash"]), units={s: _d(u) for s, u in acct["units"].items()}, keep_trades=False
    )
    memory = dict(st.get("memory") or {})
    prev = date.fromisoformat(st["last_day"]) if st.get("last_day") else None
    orders = bt.decide(p, weights(bot.params), book, history, first, prev, flow, memory)
    made = [
        BotOrder(
            bot_id=bot.id,
            decided_for=day,
            side=side,
            symbol=sym,
            requested=money.format_amount(amt.quantize(Decimal("1e-12"))),
        )
        for side, sym, amt in orders
        if amt > 0
    ]
    for o in made:
        db.add(o)
    bot.account = dict(acct)
    bot.state = {
        **st,
        "last_day": day.isoformat(),
        "flows_through": day.isoformat(),
        "memory": memory,
    }
    return made


def fill(db: DbSession, bot: Bot, prices: dict[str, Decimal], now: datetime) -> list[BotOrder]:
    """Fill the bot's waiting orders (sales first) and its twin's money at live prices."""
    p = bot.params
    acct = dict(bot.account)  # a copy: changing the stored dict in place would never be saved
    lim = bot.limits or {}
    fee = Decimal(p["fee_pct"]) / 100
    slip = Decimal(p["slippage_pct"]) / 100
    st = dict(bot.state)
    today = now.date().isoformat()
    if st.get("spent_day") != today:
        st["spent_day"], st["spent"] = today, "0"
    book = bt.Book(cash=_d(acct["cash"]), units={s: _d(u) for s, u in acct["units"].items()})
    cost = {s: _d(c) for s, c in acct["cost"].items()}
    realized = _d(acct["realized"])
    filled = []
    pending = db.scalars(
        select(BotOrder).where(BotOrder.bot_id == bot.id, BotOrder.status == "pending")
    ).all()
    for o in sorted(pending, key=lambda o: (o.side != "sell", o.id)):
        price = prices[o.symbol]
        before = len(book.trades)
        if o.side == "sell":
            units_before = book.units.get(o.symbol, Decimal(0))
            book.sell(now.date(), o.symbol, _d(o.requested), price, fee, slip)
            if len(book.trades) > before:
                t = book.trades[-1]
                sold = _d(t["units"])
                avg = cost.get(o.symbol, Decimal(0)) / units_before if units_before else Decimal(0)
                proceeds = _d(t["value"]) - _d(t["fee"])
                realized += proceeds - avg * sold
                cost[o.symbol] = cost.get(o.symbol, Decimal(0)) - avg * sold
        else:
            amount, notes = limit_buy(lim, st, _d(o.requested), book.cash)
            if notes:
                o.note = "; ".join(notes)
            book.buy(now.date(), o.symbol, amount, price, fee, slip)
            if len(book.trades) > before:
                t = book.trades[-1]
                spent = _d(t["value"]) + _d(t["fee"])
                cost[o.symbol] = cost.get(o.symbol, Decimal(0)) + spent
                st["spent"] = str(_d(st["spent"]) + spent)
        if len(book.trades) > before:
            t = book.trades[-1]
            o.status, o.filled_at = "filled", now
            o.price, o.value, o.fee = t["price"], t["value"], t["fee"]
            o.units = money.format_amount(
                _d(t["units"]).quantize(UNITS)
            )  # as shown; exact in the account
            filled.append(o)
        else:
            o.status, o.note = "cancelled", o.note or "nothing to trade"
    buy_twin(p, acct, prices, now)
    acct.update(
        cash=str(book.cash),
        units={s: str(u) for s, u in book.units.items()},
        cost={s: str(c) for s, c in cost.items()},
        realized=str(realized),
        fees=str(_d(acct["fees"]) + book.fees),
        slippage=str(_d(acct["slippage"]) + book.slippage),
    )
    bot.account = dict(acct)
    bot.state = st
    return filled


def limit_buy(lim: dict, st: dict, amount: Decimal, cash: Decimal) -> tuple[Decimal, list[str]]:
    """A buy cut to the bot's largest order and the day's spending limit (`st["spent"]` so
    far today). Paper and live alike."""
    notes = []
    if lim.get("max_order") and amount > _d(lim["max_order"]):
        amount = _d(lim["max_order"])
        notes.append("cut to the largest order")
    if lim.get("max_daily_spend"):
        room = _d(lim["max_daily_spend"]) - _d(st.get("spent"))
        if amount > room:
            amount = max(room, Decimal(0))
            notes.append("cut to the day's spending limit")
    if amount > cash:
        notes.append("cut to the cash there is")
    return amount, notes


def buy_twin(p: dict, acct: dict, prices: dict[str, Decimal], now: datetime) -> None:
    """The buy-and-hold twin (always on paper, live bots too): its new money goes straight
    into the coins, at the same prices, fee and slippage. Changes `acct` in place (a copy)."""
    twin_cash = _d(acct["bench_pending"])
    if twin_cash <= 0:
        return
    fee = Decimal(p["fee_pct"]) / 100
    slip = Decimal(p["slippage_pct"]) / 100
    twin = bt.Book(
        cash=_d(acct["bench_cash"]),
        units={s: _d(u) for s, u in acct["bench_units"].items()},
        keep_trades=False,
    )
    share = sum(weights(p).values())
    for s, w in weights(p).items():
        twin.buy(now.date(), s, twin_cash * w / share, prices[s], fee, slip)
    acct["bench_cash"] = str(twin.cash)
    acct["bench_units"] = {s: str(u) for s, u in twin.units.items()}
    acct["bench_pending"] = "0"


def summary(bot: Bot, prices: dict[str, Decimal] | None) -> dict:
    a = bot.account
    cur = bot.params["currency"]
    out = {
        "put_in": round_fiat(_d(a["put_in"]), cur),
        "cash": round_fiat(_d(a["cash"]), cur),
        "fees": round_fiat(_d(a["fees"]), cur),
        "slippage": round_fiat(_d(a["slippage"]), cur),
        "realized": round_fiat(_d(a["realized"]), cur),
        "holdings": {  # the account keeps full precision; 8 places to show
            s: money.format_amount(_d(u).quantize(UNITS))
            for s, u in a["units"].items()
            if _d(u) > 0
        },
    }
    if prices is not None:
        v, b = value_of(a, prices), value_of(a, prices, bench=True)
        put_in = _d(a["put_in"])
        unreal = sum(
            (
                _d(a["units"].get(s, 0)) * prices[s] - _d(c)
                for s, c in a["cost"].items()
                if s in prices
            ),
            Decimal(0),
        )
        out.update(
            value=round_fiat(v, cur),
            benchmark=round_fiat(b, cur),
            profit=round_fiat(v - put_in, cur),
            return_pct=round(float((v - put_in) / put_in * 100), 2) if put_in else None,
            benchmark_return_pct=round(float((b - put_in) / put_in * 100), 2) if put_in else None,
            unrealized=round_fiat(unreal, cur),
        )
    return out


def check_risk(
    db: DbSession, hub, bot: Bot, prices: dict[str, Decimal], now: datetime
) -> str | None:
    """Pause the bot, or trip the kill switch, if a limit is crossed. Returns what happened."""
    lim = bot.limits or {}
    a = bot.account
    st = dict(bot.state)
    value = value_of(a, prices)
    today = now.date().isoformat()
    if st.get("day") != today:
        st["day"], st["day_start_value"] = today, str(value)
        bot.state = st
    start_value = _d(st.get("day_start_value"))
    if lim.get("daily_loss_pct") and start_value > 0:
        drop = (start_value - value) * 100 / start_value
        if drop >= _d(lim["daily_loss_pct"]):
            reason = f"{bot.name} lost {drop:.1f} % today (its limit: {lim['daily_loss_pct']} %)"
            trip(db, hub, ACTOR, reason)
            return "kill switch"
    if lim.get("position_loss_pct"):
        for s, c in a["cost"].items():
            units = _d(a["units"].get(s, 0))
            if units > 0 and s in prices and _d(c) > 0:
                avg = _d(c) / units
                fall = (avg - prices[s]) * 100 / avg
                if fall >= _d(lim["position_loss_pct"]):
                    bot.status = "paused"
                    bot.status_reason = (
                        f"{s} is {fall:.1f} % below what it paid "
                        f"(limit {lim['position_loss_pct']} %)"
                    )[:200]
                    bot.state = {**(bot.state or {}), "paused_by": "limit"}
                    for o in db.scalars(
                        select(BotOrder).where(
                            BotOrder.bot_id == bot.id, BotOrder.status == "pending"
                        )
                    ):
                        o.status, o.note = "cancelled", "bot paused by its loss limit"
                    detail = f"{bot.name}: {bot.status_reason}"
                    record(db, "bots.pause", user_id=None, username=ACTOR, detail=detail)
                    owner = db.get(User, bot.user_id) if bot.user_id else None
                    if owner:
                        nt.notify(
                            db,
                            hub,
                            [owner],
                            category="trading",
                            level="warning",
                            title=f"{bot.name} paused: its loss limit",
                            body=bot.status_reason,
                            link="bots",
                        )
                    return "paused"
    return None


def start(db: DbSession, bot: Bot, now: datetime) -> list[BotOrder]:
    """A new bot: its first decision uses the last finished day, with its starting money."""
    yesterday = now.date() - timedelta(days=1)
    bot.state = {
        **(bot.state or {}),
        "start_day": yesterday.isoformat(),
        "clean_since": now.isoformat(timespec="seconds"),
        "last_tick_at": now.isoformat(timespec="seconds"),
    }
    if not bot.account:
        bot.account = new_account()
    made = decide(db, bot, yesterday, first=True)
    if not made and not bot.state.get("last_day"):
        # No prices for yesterday yet (just after midnight): the money waits in cash.
        bot.state = {**bot.state, "waiting_first": True}
    return made


def resume(bot: Bot, now: datetime) -> None:
    """Start a paused bot again. Its clean run carries on only after a drill; anything else
    (its limit, a real kill switch, a person pausing it) starts the two weeks again."""
    st = dict(bot.state or {})
    st.pop("day", None)  # a fresh day for the daily loss limit
    stamp = now.isoformat(timespec="seconds")
    if st.get("paused_by") != "drill" or not st.get("clean_since"):
        st["clean_since"] = stamp
        st["clean_reset"] = {"at": stamp, "why": f"started again after: {bot.status_reason}"}
    st.pop("paused_by", None)
    st["last_tick_at"] = stamp  # the paused time isn't a gap in the checks
    bot.status, bot.status_reason, bot.state = "running", None, st


# ---- the background job --------------------------------------------------------------------


class BotJob:
    def __init__(self, prices, session_factory, hub=None):
        self.prices = prices
        self.factory = session_factory
        self.hub = hub
        self.stale_since: datetime | None = None
        self.max_gap = MAX_GAP  # shorter on the readiness test clock (app/readiness.py)
        # Live bots (13c), set by app/main.py: keys are decrypted only for sending.
        self.secret_box = None
        self.settings = None
        self.test_clock = False
        self.last_result: dict = {}

    def tick(self, now: datetime | None = None) -> dict:
        from app import live
        from app.db import IMMEDIATE

        now = now or utcnow()
        with self.factory() as db:
            tripped = kill_state(db)["tripped"]
            running = db.scalars(select(Bot.id).where(Bot.status == "running")).all()
            practice = features.load(db).practice_prices
            sending = db.scalar(select(BotOrder.id).where(BotOrder.status == "sending").limit(1))
        if sending is not None and (tripped or not running or practice):
            self._live(now, {})  # real orders sent earlier: still find out what happened
        if tripped:
            return {"skipped": "the kill switch is tripped"}
        if not running:
            return {"bots": 0}
        if practice:
            return {"skipped": "practice prices are on: bots wait"}
        try:
            snap = self.prices.fresh(self.factory)  # no database session open meanwhile
            stale = snap.stale
        except PricesUnavailable:
            snap, stale = None, True
        if stale:
            self.stale_since = self.stale_since or now
            if now - self.stale_since >= STALE_TRIP:
                with self.factory() as db:
                    db.connection(execution_options={IMMEDIATE: True})
                    trip(db, self.hub, ACTOR, "prices have been stale for 15 minutes")
                    db.commit()
                live.publish(self.hub, self.factory, ["bots"])
                return {"tripped": "stale prices"}
            self._live(now, {})  # no new real orders on stale prices; lost answers still
            return {"skipped": "prices are stale"}
        self.stale_since = None
        result: dict = {"filled": 0, "decided": 0}
        changed = False  # windows only reload when there's something new to show
        live_prices_by_bot: dict[int, dict] = {}
        with self.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            coins = all_coins(db)
            for bot in db.scalars(select(Bot).where(Bot.status == "running")).all():
                if kill_state(db)["tripped"]:
                    break
                p = bot.params
                yesterday = now.date() - timedelta(days=1)
                st = dict(bot.state or {})
                stamp = now.isoformat(timespec="seconds")
                last_tick = st.get("last_tick_at")
                if last_tick and now - datetime.fromisoformat(last_tick) > self.max_gap:
                    hours = (now - datetime.fromisoformat(last_tick)).total_seconds() / 3600
                    st["clean_since"] = stamp  # the checks stopped: the clean run restarts
                    gap = f"{hours:.0f} h" if hours >= 1 else f"{hours * 60:.0f} min"
                    st["clean_reset"] = {"at": stamp, "why": f"no bot check for {gap}"}
                bot.state = st
                if st.get("waiting_first"):
                    if decide(db, bot, yesterday, first=True):
                        bot.state = {k: v for k, v in bot.state.items() if k != "waiting_first"}
                        result["decided"] += 1
                elif st.get("last_day") and date.fromisoformat(st["last_day"]) < yesterday:
                    if decide(db, bot, yesterday, first=False):
                        result["decided"] += 1
                db.flush()
                prices = live_prices(snap, coins, p["coins"], p["currency"])
                if prices is None:  # it can't trade: this check doesn't count as run
                    continue
                bot.state = {**bot.state, "last_tick_at": stamp}
                if bot.mode == "live":  # real orders go after this pass, with nothing locked
                    live_prices_by_bot[bot.id] = prices
                    acct = dict(bot.account)
                    buy_twin(p, acct, prices, now)
                    bot.account = acct
                    filled = []
                else:
                    filled = fill(db, bot, prices, now)
                result["filled"] += len(filled)
                if filled and bot.user_id:
                    owner = db.get(User, bot.user_id)
                    cur = p["currency"]
                    lines = [
                        f"{o.side} {o.symbol}"
                        + nt.detail("amounts", f" {o.units}")
                        + nt.detail(
                            "values", f" for {round_fiat(Decimal(o.value), cur)} {cur.upper()}"
                        )
                        + (f" ({o.note})" if o.note else "")  # e.g. cut to a limit
                        for o in filled
                    ]
                    if owner:
                        nt.notify(
                            db,
                            self.hub,
                            [owner],
                            category="trading",
                            title=f"{bot.name}: {len(filled)} paper order(s) filled",
                            body="; ".join(lines) + ".",
                            link="bots",
                        )
                risk = check_risk(db, self.hub, bot, prices, now)  # always, filled or not
                changed |= bool(filled or risk)
                last = (bot.state or {}).get("point_at")
                if filled or not last or now - datetime.fromisoformat(last) >= POINT_EVERY:
                    changed = True
                    db.add(
                        BotPoint(
                            bot_id=bot.id,
                            at=now,
                            value=round_fiat(value_of(bot.account, prices), p["currency"]),
                            benchmark=round_fiat(
                                value_of(bot.account, prices, True), p["currency"]
                            ),
                        )
                    )
                    bot.state = {**bot.state, "point_at": now.isoformat()}
            db.commit()
        if changed or result["decided"]:
            live.publish(self.hub, self.factory, ["bots"])
        if live_prices_by_bot or self._has_sending():
            live_out = self._live(now, live_prices_by_bot)
            result["filled"] += live_out.get("filled", 0)
            if live_out.get("sent") or live_out.get("unknown"):
                result["live"] = live_out
        self.last_result = result
        return result

    def refresh_selfcheck(self) -> None:
        """After an update changed the risk code, run the limits self-check again (it only
        uses a throwaway database). Never the first one: a person runs that deliberately."""
        from app import readiness
        from app.db import IMMEDIATE

        with self.factory() as db:
            last = readiness.report(db)["selfcheck"]
        if not last["outdated"]:
            return
        result = readiness.selfcheck()
        with self.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            readiness.save_selfcheck(db, result, "<startup>")
            failed = [r["name"] for r in result["results"] if not r["ok"]]
            detail = "passed" if result["passed"] else f"FAILED: {', '.join(failed)}"
            record(
                db,
                "bots.selfcheck",
                user_id=None,
                username="<startup>",
                detail=f"{detail} ({result['risk_code']}, the risk code changed)",
            )
            db.commit()

    def _has_sending(self) -> bool:
        with self.factory() as db:
            return (
                db.scalar(select(BotOrder.id).where(BotOrder.status == "sending").limit(1))
                is not None
            )

    def _live(self, now: datetime, prices_by_bot: dict) -> dict:
        from app import live_bots

        if self.secret_box is None:  # not set up for live bots (a bare job in a test)
            return {}
        return live_bots.run(self, now, prices_by_bot)

    async def run_forever(self) -> None:
        await asyncio.to_thread(self.refresh_selfcheck)
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # one bad pass must never stop the bots' checks for good
                log.exception("bot check failed")
            await asyncio.sleep(TICK_SECONDS)
