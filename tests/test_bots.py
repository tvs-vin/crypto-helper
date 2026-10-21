"""12d: paper trading. Bots decide on a day's close (the backtester's code), fill at the live
price with fees and slippage within their limits, have a buy-and-hold twin; the kill switch
stops everything (API and CLI) until a person re-arms it; stale prices trip it; and who may do
what."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Bot, BotOrder, DailyCandle, Notification
from app.timeutil import utcnow
from tests.conftest import H
from tests.test_users import uid
from tests.wallet_helpers import user_with

TODAY = utcnow().date()


def seed(app, symbols=("BTC", "ETH"), days=120, until=TODAY + timedelta(days=10)):
    with app.state.session_factory() as db:
        for s in symbols:
            for i in range(days):
                d = until - timedelta(days=days - 1 - i)
                db.add(DailyCandle(symbol=s, quote="usd", day=d, open="100", high="101",
                                   low="99", close="100"))  # fmt: skip
        db.commit()


PLAN = {"strategy": "dca", "coins": {"BTC": "100"}, "currency": "usd", "initial": "1000",
        "contribution": "100", "every": "week", "fee_pct": "1", "slippage_pct": "1"}  # fmt: skip


def make(c, name="DCA bot", params=None, limits=None):
    r = c.post("/api/bots", json={"name": name, "params": params or PLAN, "limits": limits or {}},
               headers=H)  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def price(app, cid="bitcoin"):
    return app.state.prices.fresh(app.state.session_factory).quotes[cid]["usd"].price


def tick(app, now=None):
    return app.state.bot_job.tick(now)


def orders(app, bot_id):
    with app.state.session_factory() as db:
        return db.scalars(
            select(BotOrder).where(BotOrder.bot_id == bot_id).order_by(BotOrder.id)
        ).all()


def bot_row(app, bot_id):
    with app.state.session_factory() as db:
        return db.get(Bot, bot_id)


@pytest.fixture
def primed(logged_in, app):
    seed(app)
    return logged_in


# ---- trading ---------------------------------------------------------------------------------


def test_a_new_bot_buys_at_the_live_price_with_fees(primed, app):
    b = make(primed)
    (o,) = orders(app, b["id"])
    assert (o.side, o.symbol, o.status, o.requested) == ("buy", "BTC", "pending", "1000")
    assert o.decided_for == TODAY - timedelta(days=1)  # yesterday's close
    assert tick(app)["filled"] == 1
    (o,) = orders(app, b["id"])
    live = price(app)
    assert o.status == "filled" and Decimal(o.price) == (live * Decimal("1.01")).quantize(
        Decimal("1e-8")
    )
    notional = Decimal(1000) / Decimal("1.01")
    assert Decimal(o.fee) == (Decimal(1000) - notional).quantize(Decimal("1e-8"))
    s = primed.get(f"/api/bots/{b['id']}").json()["summary"]
    assert s["put_in"] == "1000.00" and s["cash"] == "0.00"
    assert s["value"] == s["benchmark"]  # DCA into one coin is buy and hold
    assert Decimal(s["fees"]) > 0 and s["holdings"]["BTC"]


def test_weekly_money_arrives_and_is_invested(primed, app):
    b = make(primed)
    tick(app)
    later = utcnow() + timedelta(days=7)
    out = tick(app, later)
    assert out["decided"] == 1 and out["filled"] == 1
    last = orders(app, b["id"])[-1]
    assert last.requested == "100" and last.decided_for == later.date() - timedelta(days=1)
    s = primed.get(f"/api/bots/{b['id']}").json()["summary"]
    assert s["put_in"] == "1100.00"


def test_a_bot_waits_for_the_days_prices(logged_in, app):
    seed(app, until=TODAY - timedelta(days=5))  # nothing for yesterday yet
    b = make(logged_in)
    assert orders(app, b["id"]) == []
    assert bot_row(app, b["id"]).state.get("waiting_first") is True
    seed(app, until=TODAY + timedelta(days=3), days=8)  # the days after the first batch
    assert tick(app)["decided"] == 1  # the day's prices came in: it decides then


def test_the_same_plan_as_the_backtester(primed, app):
    """Trend: below its average it doesn't buy (the backtester's own decide())."""
    params = {**PLAN, "strategy": "trend", "ma_days": 20, "every": "none", "contribution": "0"}
    with app.state.session_factory() as db:  # yesterday's close far below its 20-day average
        c = db.scalar(
            select(DailyCandle).where(
                DailyCandle.symbol == "BTC", DailyCandle.day == TODAY - timedelta(days=1)
            )
        )
        c.close = "50"
        db.commit()
    b = make(primed, params=params)
    assert orders(app, b["id"]) == []
    assert primed.get(f"/api/bots/{b['id']}").json()["summary"]["cash"] == "1000.00"


# ---- limits ----------------------------------------------------------------------------------


def test_orders_are_cut_to_the_limits(primed, app):
    b = make(primed, limits={"max_order": "300", "max_daily_spend": "500"})
    tick(app)
    (o,) = orders(app, b["id"])
    assert Decimal(o.value) + Decimal(o.fee) == 300 and o.note == "cut to the largest order"
    s = primed.get(f"/api/bots/{b['id']}").json()["summary"]
    assert s["cash"] == "700.00"


def test_a_days_spending_is_capped(primed, app):
    b = make(primed, limits={"max_daily_spend": "400"})
    tick(app)
    (o,) = orders(app, b["id"])
    assert Decimal(o.value) + Decimal(o.fee) == 400 and o.note == "cut to the day's spending limit"


def test_a_falling_coin_pauses_the_bot(primed, app):
    b = make(primed, limits={"position_loss_pct": "10"})
    tick(app)
    with app.state.session_factory() as db:  # as if it had paid far more than today's price
        bot = db.get(Bot, b["id"])
        bot.account = {**bot.account, "cost": {"BTC": str(Decimal(bot.account["cost"]["BTC"]) * 2)}}
        db.commit()
    tick(app)
    row = bot_row(app, b["id"])
    assert row.status == "paused" and "below what it paid" in row.status_reason
    with app.state.session_factory() as db:
        assert db.scalars(select(Notification).where(Notification.category == "trading")).all()


def test_a_bad_day_trips_the_kill_switch(primed, app):
    b = make(primed, limits={"daily_loss_pct": "10"})
    tick(app)
    with app.state.session_factory() as db:  # the day started much richer
        bot = db.get(Bot, b["id"])
        bot.state = {**bot.state, "day_start_value": "100000"}
        db.commit()
    tick(app)
    k = primed.get("/api/bots").json()["kill"]
    assert k["tripped"] is True and "lost" in k["reason"]


# ---- the kill switch -------------------------------------------------------------------------


def test_kill_switch_stops_everything_until_rearmed(primed, app):
    a, b = make(primed, "One"), make(primed, "Two")
    r = primed.post("/api/bots/kill", json={"reason": "testing"}, headers=H)
    assert r.status_code == 200 and r.json()["kill"]["tripped"] is True
    assert {o.status for o in orders(app, a["id"]) + orders(app, b["id"])} == {"cancelled"}
    assert {bot_row(app, x["id"]).status for x in (a, b)} == {"paused"}
    assert tick(app) == {"skipped": "the kill switch is tripped"}
    assert primed.post(f"/api/bots/{a['id']}/start", headers=H).status_code == 409
    c = make(primed, "Three")  # made while tripped: paused
    assert c["status"] == "paused"
    assert primed.post("/api/bots/rearm", json={"confirm": "yes"}, headers=H).status_code == 422
    assert primed.post("/api/bots/rearm", json={"confirm": "REARM"}, headers=H).status_code == 200
    assert primed.post("/api/bots/rearm", json={"confirm": "REARM"}, headers=H).status_code == 409
    assert bot_row(app, a["id"]).status == "paused"  # bots start again one by one
    assert primed.post(f"/api/bots/{a['id']}/start", headers=H).json()["status"] == "running"
    actions = [e["action"] for e in primed.get("/api/audit?q=bots.").json()]
    assert "bots.kill" in actions and "bots.rearm" in actions


def test_stale_prices_trip_it_after_15_minutes(primed, app):
    make(primed)
    app.state.prices.real.fail_with = "offline"
    app.state.prices.invalidate()
    now = utcnow()
    assert tick(app, now) == {"skipped": "prices are stale"}
    assert tick(app, now + timedelta(minutes=10)) == {"skipped": "prices are stale"}
    assert tick(app, now + timedelta(minutes=16)) == {"tripped": "stale prices"}
    assert "stale" in primed.get("/api/bots").json()["kill"]["reason"]


def test_practice_prices_never_fill(primed, app):
    make(primed)
    primed.put("/api/services/features", json={"practice_prices": True}, headers=H)
    assert tick(app) == {"skipped": "practice prices are on: bots wait"}


def test_the_command_line_kill_switch(primed, app, capsys, monkeypatch):
    import app.cli.bot as bot_cli
    from app import cli

    make(primed)
    # The CLI opens the install's database; here, this app's (an in-memory one can't be shared).
    monkeypatch.setattr(bot_cli, "open_db", lambda settings: (None, app.state.session_factory))
    assert cli.main(["bot", "stop"]) == 1  # needs --all: it's the kill switch
    assert cli.main(["bot", "stop", "--all", "--reason", "drill"]) == 0
    assert "Kill switch tripped" in capsys.readouterr().out
    assert primed.get("/api/bots").json()["kill"]["reason"] == "drill"
    assert cli.main(["bot", "list"]) == 0
    assert "TRIPPED" in capsys.readouterr().out
    assert cli.main(["bot", "rearm", "--yes"]) == 0
    assert primed.get("/api/bots").json()["kill"]["tripped"] is False
    entry = primed.get("/api/audit?q=bots.kill").json()[0]
    assert entry["username"] == "<cli>" and entry["detail"].startswith("drill")


# ---- the rules -------------------------------------------------------------------------------


def test_who_may_do_what(primed, app):
    b = make(primed)
    viewer = user_with(app, primed, "botviewer", ["bots.view"])
    assert viewer.get("/api/bots").status_code == 200
    assert viewer.get(f"/api/bots/{b['id']}").status_code == 200
    assert (
        viewer.post("/api/bots", json={"name": "x", "params": PLAN}, headers=H).status_code == 403
    )
    assert viewer.post("/api/bots/kill", json={}, headers=H).status_code == 403
    stopper = user_with(app, primed, "stopper", ["bots.view", "bots.stop"])
    assert stopper.post("/api/bots/kill", json={}, headers=H).status_code == 200
    r = stopper.post("/api/bots/rearm", json={"confirm": "REARM"}, headers=H)
    assert r.status_code == 403  # stopping is easy; starting again needs bots.run
    nobody = user_with(app, primed, "nobody", ["prices.view"])
    assert nobody.get("/api/bots").status_code == 403


def test_a_seed_phrase_is_never_a_bot_name(primed):
    seedphrase = " ".join(["zoo"] * 11 + ["wrong"])  # a valid 12-word phrase
    r = primed.post("/api/bots", json={"name": seedphrase, "params": PLAN}, headers=H)
    assert r.status_code == 422 and "zoo" not in r.text


@pytest.mark.parametrize(
    ("params", "limits", "message"),
    [
        ({**PLAN, "coins": {"BTC": "50"}}, {}, "add up to 100"),
        ({**PLAN, "fee_pct": "50"}, {}, "fee must be between"),
        (PLAN, {"daily_loss_pct": "0"}, "daily loss pct must be between"),
        ({**PLAN, "coins": {"NOPE": "100"}}, {}, "No coin NOPE"),
        ({**PLAN, "surprise": 1}, {}, "Extra inputs"),
    ],
)
def test_bad_bots_are_refused(primed, params, limits, message):
    r = primed.post("/api/bots", json={"name": "x", "params": params, "limits": limits}, headers=H)
    assert r.status_code == 422 and message in r.json()["detail"], r.text


def test_orders_csv_delete_and_audit(primed, app):
    b = make(primed, "=csv bot")
    tick(app)
    csv = primed.get(f"/api/bots/{b['id']}/orders.csv")
    lines = csv.text.strip().splitlines()
    assert lines[0].startswith("decided_for,filled_at,side") and len(lines) == 2
    assert primed.delete(f"/api/bots/{b['id']}", headers=H).status_code == 204
    assert primed.get(f"/api/bots/{b['id']}").status_code == 404
    actions = [e["action"] for e in primed.get("/api/audit?q=bots.").json()]
    assert actions[:2] == ["bots.delete", "bots.create"]
    assert uid(app, "super")
