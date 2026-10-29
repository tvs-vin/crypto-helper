"""13c: live bots, against the demo exchange (no network, made-up fills). A live bot decides
like a paper bot; its orders go to the exchange, within every gate (readiness, the switch, the
key, the owner's permissions, the cap), with our own id, and the real fill is recorded."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import readiness
from app.models import Bot, BotOrder, Notification, TradingKey, User
from app.orders import OrderError, Rules, demo
from app.timeutil import utcnow
from tests.conftest import H
from tests.test_bots import PLAN, seed, tick
from tests.test_totp import enrol
from tests.test_trading import enrol as enrol_user
from tests.wallet_helpers import user_with

LIVE_PLAN = {
    **PLAN,
    "initial": "100",
    "contribution": "0",
    "every": "none",
    "fee_pct": "0.6",
    "slippage_pct": "0",
}


def green(app, c):
    """Ready for live trading: a paper bot with 15 clean days, a drill, the self-check."""
    r = c.post("/api/bots", json={"name": "Paper proof", "params": PLAN}, headers=H)
    pid = r.json()["id"]
    assert c.post("/api/bots/drill", json={}, headers=H).status_code == 200
    c.post("/api/bots/rearm", json={"confirm": "REARM"}, headers=H)
    c.post(f"/api/bots/{pid}/start", headers=H)
    c.post("/api/bots/selfcheck", headers=H)
    with app.state.session_factory() as db:
        b = db.get(Bot, pid)
        b.state = {
            **b.state,
            "clean_since": (utcnow() - timedelta(days=15)).isoformat(),
            "last_tick_at": utcnow().isoformat(),
        }
        db.commit()
    with app.state.session_factory() as db:
        assert readiness.report(db)["live_allowed"]


def stay_green(monkeypatch):
    """For tests that jump days ahead (the proof bot's clean run would restart): readiness is
    tested on its own (tests/test_readiness.py)."""
    import app.live_bots as lb

    real = lb.readiness.report
    monkeypatch.setattr(
        lb.readiness, "report", lambda db, **kw: {**real(db, **kw), "live_allowed": True}
    )


@pytest.fixture
def live(logged_in, app, monkeypatch):
    from app.sync import demo as sync_demo

    monkeypatch.setitem(sync_demo.BALANCES, "XBT", "1000")  # the account holds what bots buy
    seed(app)
    logged_in.secret, _ = enrol(logged_in)
    logged_in.put("/api/services/live", json={"exchange": "demo", "on": True}, headers=H)
    r = logged_in.post(
        "/api/trading/keys",
        json={
            "kind": "demo",
            "label": "Demo",
            "credentials": {"key": "demo-key-1234", "secret": "x"},
        },
        headers=H,
    )
    assert r.status_code == 201, r.text
    logged_in.key_id = r.json()["id"]
    r = first_order(logged_in, logged_in.key_id)  # what a person does once per key
    assert r.status_code == 200 and r.json()["status"] == "filled", r.text
    green(app, logged_in)
    demo.PLACED.clear()
    return logged_in


def first_order(c, key_id, coin="BTC", step=1):
    """The key's first tiny order, with a 2FA code (the next 30-second window's: each code
    works once, so a second order in one test needs `codes_always_fit`)."""
    from tests.test_totp import code

    body = {"coin": coin, "code": code(c.secret, step)}
    return c.post(f"/api/trading/keys/{key_id}/first-order", json=body, headers=H)


def codes_always_fit(monkeypatch):
    """For tests that need more 2FA codes than real time gives them (as tests/test_shell.py)."""
    from app import totp

    monkeypatch.setattr(totp, "verify_totp", lambda secret, c, last: (last or 0) + 1)


def make_live(c, key_id=None, name="Live BTC", params=None, **kw):
    body = {
        "name": name,
        "params": params or LIVE_PLAN,
        "mode": "live",
        "trading_key_id": key_id or c.key_id,
        **kw,
    }
    return c.post("/api/bots", json=body, headers=H)


def orders_of(app, bot_id):
    with app.state.session_factory() as db:
        return db.scalars(select(BotOrder).where(BotOrder.bot_id == bot_id)).all()


def bot(app, bot_id):
    with app.state.session_factory() as db:
        return db.get(Bot, bot_id)


def set_key(app, key_id, key):
    import json

    with app.state.session_factory() as db:
        k = db.get(TradingKey, key_id)
        k.secret_encrypted = app.state.secret_box.encrypt(json.dumps({"key": key, "secret": "x"}))
        db.commit()


# ---- trading ---------------------------------------------------------------------------------


def test_a_live_bot_places_a_real_order_and_records_the_fill(live, app):
    r = make_live(live)
    assert r.status_code == 201, r.text
    b = r.json()
    assert (
        b["mode"] == "live"
        and b["live"]["exchange"] == "demo"
        and b["live"]["order_kind"] == "limit"
    )
    out = tick(app)
    assert out["live"]["sent"] == 1 and out["filled"] >= 1
    (o,) = orders_of(app, b["id"])
    assert o.status == "filled" and o.client_id.startswith("ch-") and o.exchange_order_id
    assert demo.PLACED[o.client_id].base == Decimal(o.units)  # the exchange's own record
    row = bot(app, b["id"])
    spent = Decimal(o.value) + Decimal(o.fee)
    assert Decimal(row.account["cash"]) == Decimal("100") - spent
    assert Decimal(row.account["cash"]) >= 0  # the fee had room: never more than its cash
    assert Decimal(row.account["units"]["BTC"]) == Decimal(o.units)
    assert Decimal(row.state["reserved"]) == 0
    with app.state.session_factory() as db:
        n = db.scalars(select(Notification).where(Notification.category == "trading")).all()
        assert any("real order(s) filled" in x.title for x in n)


def test_no_live_bot_before_its_first_tiny_order_or_readiness(logged_in, app):
    seed(app)
    logged_in.secret, _ = enrol(logged_in)
    logged_in.put("/api/services/live", json={"exchange": "demo", "on": True}, headers=H)
    k = logged_in.post(
        "/api/trading/keys",
        json={"kind": "demo", "label": "D", "credentials": {"key": "demo-k-1234", "secret": "x"}},
        headers=H,
    ).json()
    r = make_live(logged_in, k["id"])
    assert r.status_code == 409 and "first tiny order" in r.json()["detail"]
    assert first_order(logged_in, k["id"]).json()["status"] == "filled"  # allowed before green
    r = make_live(logged_in, k["id"])
    assert r.status_code == 409 and "rule 10" in r.json()["detail"]


def test_the_cap_limits_the_money_a_live_bot_is_given(live, app, monkeypatch):
    stay_green(monkeypatch)
    seed(app, until=utcnow().date() + timedelta(days=30), days=20)  # prices for weeks ahead
    r = make_live(live, params={**LIVE_PLAN, "initial": "200"})
    assert r.status_code == 422 and "cap leaves $150.00" in r.json()["detail"]
    weekly = {**LIVE_PLAN, "contribution": "100", "every": "week"}
    b = make_live(live, params=weekly).json()
    tick(app)
    tick(app, utcnow() + timedelta(days=7))
    row = bot(app, b["id"])
    assert row.account["put_in"] == "150" and row.state["cap_cut"]["given"] == "50"
    with app.state.session_factory() as db:  # an admin lowers the cap: no more buys
        u = db.scalar(select(User).where(User.username == "super"))
        u.live_cap = "50"
        db.commit()
    tick(app, utcnow() + timedelta(days=14))
    assert bot(app, b["id"]).state["cap_cut"]["given"] == "0"  # no new money past the cap
    with app.state.session_factory() as db:  # a buy from cash it already has (e.g. rebalancing)
        db.add(
            BotOrder(
                bot_id=b["id"],
                side="buy",
                symbol="BTC",
                requested="10",
                created_at=utcnow() + timedelta(days=14),
            )
        )
        db.commit()
    tick(app, utcnow() + timedelta(days=14, minutes=1))
    last = orders_of(app, b["id"])[-1]
    assert last.status == "cancelled" and "over your cap" in last.note


def test_the_kill_switch_stops_live_orders(live, app):
    b = make_live(live).json()
    live.post("/api/bots/kill", json={"reason": "stop"}, headers=H)
    assert tick(app) == {"skipped": "the kill switch is tripped"}
    assert demo.PLACED == {}
    assert {o.status for o in orders_of(app, b["id"])} == {"cancelled"}


@pytest.mark.parametrize("what", ["exchange off", "key deleted", "permission taken"])
def test_every_gate_pauses_the_bot_with_its_reason(live, app, what):
    b = make_live(live).json()
    if what == "exchange off":
        live.put("/api/services/live", json={"exchange": "demo", "on": False}, headers=H)
        expect = "switched off"
    elif what == "key deleted":
        assert live.delete(f"/api/trading/keys/{live.key_id}", headers=H).status_code == 204
        expect = "trading key was deleted"
    else:
        with app.state.session_factory() as db:
            u = db.scalar(select(User).where(User.username == "super"))
            u.totp_enabled = False  # (super holds every permission: 2FA is what goes)
            db.commit()
        expect = "may no longer trade"
    tick(app)
    row = bot(app, b["id"])
    assert row.status == "paused" and expect in row.status_reason
    assert demo.PLACED == {}


# ---- the exchange's answers ------------------------------------------------------------------


def test_a_lost_answer_is_looked_up_never_resent(live, app):
    set_key(app, live.key_id, "lost-key-1234")
    b = make_live(live).json()
    now = utcnow()
    out = tick(app, now)
    assert out["live"]["unknown"] == 1
    (o,) = orders_of(app, b["id"])
    assert o.status == "sending" and Decimal(bot(app, b["id"]).state["reserved"]) > 0
    tick(app, now + timedelta(minutes=1))  # too soon: still waiting for the answer
    assert len(demo.PLACED) == 1 and orders_of(app, b["id"])[0].status == "sending"
    tick(app, now + timedelta(minutes=3))
    (o,) = orders_of(app, b["id"])
    assert o.status == "filled" and len(demo.PLACED) == 1  # found, not sent again
    assert Decimal(bot(app, b["id"]).state["reserved"]) == 0


@pytest.mark.parametrize(
    ("key", "status", "units"),
    [("nofill-key-1", "cancelled", False), ("half-key-123", "partial", True)],
)
def test_nothing_or_half_filled(live, app, key, status, units):
    set_key(app, live.key_id, key)
    b = make_live(live).json()
    tick(app)
    (o,) = orders_of(app, b["id"])
    assert o.status == status
    row = bot(app, b["id"])
    assert bool(row.account["units"].get("BTC")) is units
    assert Decimal(row.state["reserved"]) == 0
    if not units:
        assert row.account["cash"] == "100" and "moved past the protection" in o.note


def test_a_refusal_pauses_the_bot(live, app, monkeypatch):
    def refuse(self, creds, order):
        raise OrderError("Insufficient funds")

    monkeypatch.setattr(demo.DemoOrders, "place", refuse)
    b = make_live(live).json()
    tick(app)
    row = bot(app, b["id"])
    assert row.status == "paused" and "Insufficient funds" in row.status_reason
    assert row.account["cash"] == "100" and row.state["spent"] == "0"


def test_the_exchange_holding_less_than_the_bots_think_pauses_them(live, app, monkeypatch):
    b = make_live(live).json()
    tick(app)
    from app.sync import demo as sync_demo

    monkeypatch.setitem(sync_demo.BALANCES, "XBT", "0.00000001")  # sold by hand on the exchange
    app.state.bot_job.last_reconcile = utcnow() - timedelta(hours=2)
    tick(app)
    row = bot(app, b["id"])
    assert row.status == "paused" and "holds less BTC" in row.status_reason


# ---- who may ---------------------------------------------------------------------------------


def test_a_live_bot_is_its_owners(live, app):
    b = make_live(live).json()
    other = user_with(app, live, "botpeer", ["bots.view", "bots.run"])
    assert all(x["id"] != b["id"] for x in other.get("/api/bots").json()["bots"])
    for path in (f"/api/bots/{b['id']}", f"/api/bots/{b['id']}/orders.csv"):
        assert other.get(path).status_code == 404
    assert other.post(f"/api/bots/{b['id']}/pause", headers=H).status_code == 404
    assert other.delete(f"/api/bots/{b['id']}", headers=H).status_code == 404
    trader = user_with(app, live, "notlive", ["bots.view", "bots.run"])
    enrol_user(trader)
    r = make_live(trader, key_id=live.key_id)
    assert r.status_code == 403 and "live.trade" in r.json()["detail"]


def test_no_deleting_a_bot_or_key_while_an_order_is_on_its_way(live, app):
    set_key(app, live.key_id, "lost-key-5678")
    b = make_live(live).json()
    tick(app)
    assert live.delete(f"/api/bots/{b['id']}", headers=H).status_code == 409
    assert live.delete(f"/api/trading/keys/{live.key_id}", headers=H).status_code == 409


def test_an_update_reruns_an_outdated_selfcheck(live, app, monkeypatch):
    monkeypatch.setattr(readiness, "risk_code", lambda: "changed-code")
    app.state.bot_job.refresh_selfcheck()
    entry = live.get("/api/audit?q=bots.selfcheck").json()[0]
    assert entry["username"] == "<startup>" and "the risk code changed" in entry["detail"]
    with app.state.session_factory() as db:
        assert readiness.report(db)["selfcheck"]["ok"]


def test_readiness_turning_red_pauses_live_bots(live, app, monkeypatch):
    b = make_live(live).json()
    monkeypatch.setattr(readiness, "risk_code", lambda: "the engine changed")  # self-check stale
    tick(app)
    row = bot(app, b["id"])
    assert row.status == "paused" and "Ready for live trading isn't green" in row.status_reason
    assert demo.PLACED == {}


def test_why_not_names_every_gate(live, app):
    import app.live_bots as lb

    b = make_live(live).json()
    ctx = app.state.bot_job
    with app.state.session_factory() as db:
        row = db.get(Bot, b["id"])
        assert lb.why_not(db, row, False, ctx.settings) is None
        owner = db.get(User, row.user_id)
        owner.is_active = False
        assert "deactivated" in lb.why_not(db, row, False, ctx.settings)
        owner.is_active = True
        from app.bots import trip

        trip(db, None, "test", "testing")
        assert lb.why_not(db, row, False, ctx.settings) == "the kill switch is tripped"
        db.rollback()


# ---- the first tiny order (13d) --------------------------------------------------------------


def test_the_first_tiny_order(live, app, monkeypatch):
    codes_always_fit(monkeypatch)
    k = live.post(
        "/api/trading/keys",
        json={
            "kind": "demo",
            "label": "Second",
            "credentials": {"key": "demo-key-9999", "secret": "x"},
        },
        headers=H,
    ).json()
    assert "no first tiny order yet" in k["check"]
    p = live.post(
        f"/api/trading/keys/{k['id']}/first-order/preview", json={"coin": "BTC"}, headers=H
    ).json()
    assert Decimal(p["at_most"]) <= 25 and Decimal(p["size"]) > 0 and p["symbol"] == "BTC-USD"
    placed = dict(demo.PLACED)
    r = live.post(f"/api/trading/keys/{k['id']}/first-order", json={"coin": "BTC"}, headers=H)
    assert r.status_code == 403 and demo.PLACED == placed  # no code, no order
    r = first_order(live, k["id"])
    assert r.status_code == 200 and r.json()["status"] == "filled"
    assert "first tiny order done" in r.json()["key"]["check"]
    assert first_order(live, k["id"]).status_code == 409  # once is enough
    entry = live.get("/api/audit?q=trading.key.firstorder").json()[0]
    assert "Done: bought" in entry["detail"]


def test_a_lost_first_order_is_looked_up_not_repeated(live, app, monkeypatch):
    codes_always_fit(monkeypatch)
    k = live.post(
        "/api/trading/keys",
        json={
            "kind": "demo",
            "label": "Lossy",
            "credentials": {"key": "lost-key-7777", "secret": "x"},
        },
        headers=H,
    ).json()
    r = first_order(live, k["id"]).json()
    assert r["status"] == "unknown" and "press again" in r["message"]
    count = len(demo.PLACED)
    r = first_order(live, k["id"]).json()
    assert r["status"] == "filled" and len(demo.PLACED) == count  # found, not placed again


def test_a_first_order_that_isnt_tiny_is_refused(live, app, monkeypatch):
    codes_always_fit(monkeypatch)
    real = demo.DemoOrders.rules
    monkeypatch.setattr(
        demo.DemoOrders,
        "rules",
        lambda self, b, q: Rules(**{**real(self, b, q).__dict__, "quote_min": Decimal("40")}),
    )
    k = live.post(
        "/api/trading/keys",
        json={
            "kind": "demo",
            "label": "Big",
            "credentials": {"key": "demo-key-8888", "secret": "x"},
        },
        headers=H,
    ).json()
    r = first_order(live, k["id"])
    assert r.status_code == 409 and "isn't tiny" in r.json()["detail"]


# ---- when things go wrong (13d) --------------------------------------------------------------


def test_exchange_unreachable_before_sending_puts_the_order_back(live, app, monkeypatch):
    from app.sync import SourceError

    b = make_live(live).json()
    real = demo.DemoOrders.rules
    monkeypatch.setattr(
        demo.DemoOrders,
        "rules",
        lambda *a: (_ for _ in ()).throw(SourceError("Couldn't reach Demo (timed out)")),
    )
    tick(app)
    (o,) = orders_of(app, b["id"])
    assert o.status == "pending" and "couldn't be reached" in o.note and o.client_id is None
    assert (
        Decimal(bot(app, b["id"]).state["reserved"]) == 0 and bot(app, b["id"]).status == "running"
    )
    monkeypatch.setattr(demo.DemoOrders, "rules", real)
    tick(app, utcnow() + timedelta(minutes=1))
    assert orders_of(app, b["id"])[0].status == "filled"


def test_a_refused_key_pauses_with_the_allowlist_hint(live, app, monkeypatch):
    def refused(self, creds, order):
        raise OrderError("Demo refused the key (401)", final=True)

    monkeypatch.setattr(demo.DemoOrders, "place", refused)
    b = make_live(live).json()
    tick(app)
    row = bot(app, b["id"])
    assert row.status == "paused" and "allowlist" in row.status_reason


def test_a_restart_mid_order_finds_it_again(live, app):
    from app.bots import BotJob

    set_key(app, live.key_id, "lost-key-2468")
    b = make_live(live).json()
    now = utcnow()
    tick(app, now)
    assert orders_of(app, b["id"])[0].status == "sending"
    old = app.state.bot_job  # the server restarts: a new job, knowing nothing in memory
    new = BotJob(old.prices, app.state.session_factory, old.hub)
    new.secret_box, new.settings = old.secret_box, old.settings
    new.tick(now + timedelta(minutes=3))
    (o,) = orders_of(app, b["id"])
    assert o.status == "filled" and len(demo.PLACED) == 1


def test_an_outcome_unknown_for_30_minutes_pauses_the_bot(live, app, monkeypatch):
    set_key(app, live.key_id, "lost-key-1357")
    monkeypatch.setattr(
        demo.DemoOrders,
        "lookup",
        lambda self, creds, order: (_ for _ in ()).throw(
            OrderError("Couldn't reach Demo", unknown=True)
        ),
    )
    b = make_live(live).json()
    now = utcnow()
    tick(app, now)
    tick(app, now + timedelta(minutes=3))
    assert bot(app, b["id"]).status == "running"
    tick(app, now + timedelta(minutes=31))
    row = bot(app, b["id"])
    assert row.status == "paused" and "still unknown after 30 minutes" in row.status_reason
    assert orders_of(app, b["id"])[0].status == "sending"  # it keeps being looked up


def test_a_day_old_order_is_dropped(live, app):
    b = make_live(live).json()
    with app.state.session_factory() as db:
        o = db.scalars(select(BotOrder).where(BotOrder.bot_id == b["id"])).one()
        o.created_at = utcnow() - timedelta(days=2)
        db.commit()
    tick(app)
    (o,) = orders_of(app, b["id"])
    assert o.status == "cancelled" and "too old" in o.note and demo.PLACED == {}


def test_a_drill_counts_live_bots(live, app):
    make_live(live)
    k = live.post("/api/bots/drill", json={}, headers=H).json()["kill"]
    assert k["drill"]["live_stopped"] == 1


def test_the_bot_check_itself_needs_the_first_tiny_order(live, app):
    """Bot creation checks it too; this is the gate right before every real order."""
    b = make_live(live).json()
    with app.state.session_factory() as db:
        k = db.get(TradingKey, live.key_id)
        k.check = {x: v for x, v in k.check.items() if x != "first_order"}
        db.commit()
    tick(app)
    row = bot(app, b["id"])
    assert row.status == "paused" and "first tiny order" in row.status_reason
    assert demo.PLACED == {}  # nothing from the bot (the fixture cleared its first order)
