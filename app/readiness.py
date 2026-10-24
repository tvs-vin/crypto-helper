"""Readiness for live trading (12e): project rule 10, checked by the app. No unattended live
trading (phase 4) until:

1. a bot has **run cleanly on paper for 14 days** in a row: running the whole time, with its
   risk limits set, and nothing went wrong. Its clean run starts again when its loss limit
   pauses it, the kill switch trips for real, a person pauses it, or the bot check stops for
   more than 6 hours (the service was down, or prices were stale or practice ones). A drill
   doesn't count against it.
2. the **kill switch has been tested**: a drill in the last 90 days, completed by re-arming,
   that stopped every bot, cancelled every waiting order, and made the bot check refuse to
   trade.
3. the **loss limits are enforced in code**: the limits self-check (below) passed with the
   risk code this install is running now.

The self-check runs the real engine (`app/bots.py`) against a throwaway in-memory database,
so it can run on a live install without touching its data.

The **test clock** (`BOT_READINESS_TEST_CLOCK`, development and throwaway test servers only)
makes a day a minute, so the whole flow can be tried in minutes. It is refused on an install's
own database or as the service account, and a report made on it never allows live trading:
`live_allowed` (what phase 4's switch must check) is only true on the real clock.
"""

import hashlib
import inspect
import os
import pwd
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import bots
from app.models import AppSetting, Base, Bot, BotOrder
from app.timeutil import utcnow

CLEAN_DAYS = 14
DRILL_DAYS = 90
SELFCHECK_KEY = "limits_selfcheck"
TEST_DAY = timedelta(minutes=1)  # a "day" on the test clock
TEST_GAP = timedelta(minutes=5)  # the 6-hour gap on the test clock (the check runs each minute)


class TestClockRefused(SystemExit):
    pass


def test_clock(settings) -> bool:
    """Whether the test clock is on. Never on an install's own data: refused (the server won't
    start) if the database is the installed one or this runs as the service account."""
    if not getattr(settings, "readiness_test_clock", False):
        return False
    from pathlib import Path

    from app.cli.layout import NAME, current_layout

    url = settings.database_url
    path = url.removeprefix("sqlite:///") if url.startswith("sqlite:///") else None
    installed_db = current_layout().db
    on_install = bool(path) and Path(path).resolve() == installed_db.resolve()
    try:
        service_account = pwd.getpwuid(os.getuid()).pw_name == NAME
    except KeyError:
        service_account = False
    if on_install or service_account:
        raise TestClockRefused(
            "BOT_READINESS_TEST_CLOCK is for development and test servers only: it's refused "
            "on an install's own database (rule 10 needs the real 14 days there)."
        )
    return True


def _day(test: bool) -> timedelta:
    return TEST_DAY if test else timedelta(days=1)


def _gap(test: bool) -> timedelta:
    return TEST_GAP if test else bots.MAX_GAP


def risk_code() -> str:
    """A fingerprint of the risk code running now: a changed engine needs a new self-check."""
    return hashlib.sha256(inspect.getsource(bots).encode()).hexdigest()[:12]


# ---- the limits self-check -------------------------------------------------------------------


class _Snap:
    def __init__(self, stale: bool):
        self.stale, self.quotes = stale, {}


class _Prices:
    """Stands in for the price service: the self-check never fetches anything."""

    def __init__(self, stale: bool):
        self.stale = stale

    def fresh(self, factory):
        return _Snap(self.stale)


def _scenarios():
    """(name, what it shows, function(db) -> problem or None). Each gets a fresh database."""
    now = utcnow()
    price = {"BTC": Decimal("100")}
    plan = {"strategy": "dca", "coins": {"BTC": "100"}, "currency": "usd", "initial": "1000",
            "fee_pct": "1", "slippage_pct": "0"}  # fmt: skip
    plan, _ = bots.validate(plan, {})

    def bot(db, limits=None, cash="1000"):
        _, lim = bots.validate(plan, limits or {})
        b = Bot(name="self-check", params=plan, limits=lim, status="running",
                account={**bots.new_account(), "cash": cash, "put_in": cash},
                state={"clean_since": now.isoformat()})  # fmt: skip
        db.add(b)
        db.flush()
        return b

    def buy(db, b, amount):
        db.add(BotOrder(bot_id=b.id, side="buy", symbol="BTC", requested=amount))
        db.flush()

    def largest_order(db):
        b = bot(db, {"max_order": "100"})
        buy(db, b, "500")
        (o,) = bots.fill(db, b, price, now)
        spent = Decimal(o.value) + Decimal(o.fee)
        return None if spent == 100 else f"a 500 buy with a 100 limit spent {spent}"

    def daily_spend(db):
        b = bot(db, {"max_daily_spend": "150"})
        buy(db, b, "100")
        buy(db, b, "100")
        filled = bots.fill(db, b, price, now)
        spent = sum(Decimal(o.value) + Decimal(o.fee) for o in filled)
        return None if spent == 150 else f"two 100 buys with a 150 day limit spent {spent}"

    def position_loss(db):
        b = bot(db, {"position_loss_pct": "20"})
        buy(db, b, "1000")
        bots.fill(db, b, price, now)
        bots.check_risk(db, None, b, {"BTC": Decimal("70")}, now)  # 30 % below
        return None if b.status == "paused" else "a 30 % fall with a 20 % limit didn't pause"

    def daily_loss(db):
        b = bot(db, {"daily_loss_pct": "10", "position_loss_pct": None})
        buy(db, b, "1000")
        bots.fill(db, b, price, now)
        bots.check_risk(db, None, b, price, now)  # the day starts here
        bots.check_risk(db, None, b, {"BTC": Decimal("80")}, now)
        ok = bots.kill_state(db)["tripped"] and b.status == "paused"
        return None if ok else "losing 20 % in a day with a 10 % limit didn't trip the switch"

    def kill_blocks(db):
        b = bot(db)
        buy(db, b, "100")
        bots.trip(db, None, "<self-check>", "self-check")
        db.commit()
        o = db.scalar(select(BotOrder))
        answer = bots.BotJob(_Prices(False), _factory_of(db)).tick(now)
        if o.status != "cancelled" or answer != {"skipped": "the kill switch is tripped"}:
            return f"the tripped switch let the check run ({answer}, order {o.status})"
        return None

    def stale_waits(db):
        b = bot(db)
        buy(db, b, "100")
        db.commit()
        job = bots.BotJob(_Prices(True), _factory_of(db))
        answer = job.tick(now)
        tripped = job.tick(now + bots.STALE_TRIP)
        if answer != {"skipped": "prices are stale"} or tripped != {"tripped": "stale prices"}:
            return f"stale prices: {answer}, then {tripped}"
        return None

    return [
        ("largest order", "a bigger buy is cut to the limit", largest_order),
        ("day's spending", "buys past the day's limit are cut", daily_spend),
        ("coin's loss", "a coin falling past its limit pauses the bot", position_loss),
        ("day's loss", "the bot losing its daily limit trips the kill switch", daily_loss),
        ("kill switch", "a tripped switch cancels orders and the check won't trade", kill_blocks),
        ("stale prices", "no trading on stale prices; 15 minutes of them trip the switch",
         stale_waits),
    ]  # fmt: skip


def _factory_of(db: DbSession):
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


def selfcheck() -> dict:
    """Run every scenario on its own throwaway in-memory database. Never touches the install's."""
    results = []
    for name, shows, fn in _scenarios():
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        try:
            with sessionmaker(bind=engine, expire_on_commit=False)() as db:
                problem = fn(db)
        except Exception as e:  # a crash is a failed check, reported, not a broken page
            problem = f"crashed: {type(e).__name__}: {e}"
        finally:
            engine.dispose()
        results.append({"name": name, "shows": shows, "ok": problem is None, "problem": problem})
    return {
        "at": utcnow().isoformat(timespec="seconds"),
        "risk_code": risk_code(),
        "passed": all(r["ok"] for r in results),
        "results": results,
    }


def save_selfcheck(db: DbSession, result: dict, by: str) -> None:
    row = db.get(AppSetting, SELFCHECK_KEY)
    if row is None:
        db.add(AppSetting(key=SELFCHECK_KEY, value=result, updated_by=by))
    else:
        row.value, row.updated_by = result, by


# ---- the report ------------------------------------------------------------------------------


def _clean_days(b: Bot, now: datetime, test: bool = False) -> float:
    if b.status != "running":
        return 0.0
    last = (b.state or {}).get("last_tick_at")
    if last and now - datetime.fromisoformat(last) > _gap(test):
        return 0.0  # no bot check with prices for 6 hours: stopped or stuck right now
    since = (b.state or {}).get("clean_since")
    start = datetime.fromisoformat(since) if since else b.created_at
    return max(0.0, (now - start) / _day(test))


def _ready_on(st: dict, days: float, test: bool) -> str | None:
    """When the bot's clean run reaches 14 days: a date (a minute on the test clock)."""
    if not st.get("clean_since") or days >= CLEAN_DAYS:
        return None
    at = datetime.fromisoformat(st["clean_since"]) + CLEAN_DAYS * _day(test)
    return at.isoformat(timespec="minutes") if test else at.date().isoformat()


def report(db: DbSession, now: datetime | None = None, test: bool = False) -> dict:
    """`test`: the test clock (see test_clock()); the report then never allows live trading."""
    now = now or utcnow()
    out_bots = []
    for b in db.scalars(select(Bot).order_by(Bot.id)):
        lim = b.limits or {}
        days = _clean_days(b, now, test)
        st = b.state or {}
        last = st.get("last_tick_at")
        stuck = bool(
            b.status == "running" and last and now - datetime.fromisoformat(last) > _gap(test)
        )
        checks = [
            {
                "key": "running",
                "ok": b.status == "running",
                "label": "Running",
                "detail": "running" if b.status == "running" else f"paused: {b.status_reason}",
            },
            {
                "key": "limits",
                "ok": bool(lim.get("position_loss_pct") and lim.get("daily_loss_pct")),
                "label": "Loss limits set",
                "detail": f"a coin's loss {lim.get('position_loss_pct') or 'none'} %, "
                f"a day's loss {lim.get('daily_loss_pct') or 'none'} %",
            },
            {
                "key": "clean",
                "ok": days >= CLEAN_DAYS,
                "label": f"{CLEAN_DAYS} clean days on paper",
                "detail": f"{days:.1f} of {CLEAN_DAYS} days"
                + (" (no bot check with prices for over 6 hours)" if stuck else ""),
            },
        ]
        out_bots.append(
            {
                "id": b.id,
                "name": b.name,
                "ok": all(c["ok"] for c in checks),
                "clean_days": round(days, 2),
                "clean_since": st.get("clean_since") if b.status == "running" else None,
                "ready_on": _ready_on(st, days, test) if b.status == "running" else None,
                "last_reset": st.get("clean_reset"),
                "checks": checks,
            }
        )
    done = [
        d
        for d in bots.drills(db)
        if d.get("all_stopped") and d.get("check_refused") and d.get("rearmed_at")
    ]
    recent = [d for d in done if now - datetime.fromisoformat(d["at"]) <= DRILL_DAYS * _day(test)]
    k = bots.kill_state(db)
    drill = {
        "ok": bool(recent),
        "last": (bots.drills(db) or [None])[0],
        "in_progress": bool(k["tripped"] and k.get("drill") is not None),
        "days": DRILL_DAYS,
    }
    row = db.get(AppSetting, SELFCHECK_KEY)
    last = row.value if row else None
    current = risk_code()
    check = {
        "ok": bool(last and last["passed"] and last["risk_code"] == current),
        "last": last,
        "outdated": bool(last and last["risk_code"] != current),
    }
    ready = any(b["ok"] for b in out_bots) and drill["ok"] and check["ok"]
    return {
        "ready": ready,
        # What phase 4's "go live" switch must check: ready, on the real clock.
        "live_allowed": ready and not test,
        "test_clock": test,
        "clean_days": CLEAN_DAYS,
        "bots": out_bots,
        "drill": drill,
        "selfcheck": check,
    }
