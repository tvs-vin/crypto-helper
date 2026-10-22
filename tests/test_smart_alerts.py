"""12a: the smarter alerts. Each kind fires once and re-arms (a moving-average cross fires per
change of side); wallet changes come from a real sync of the Demo exchange; what reaches Discord
depends on each person's detail switches; and the rules about who may have which alert."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import notifications as nt
from app import smart_alerts as sa
from app.models import Alert, BalancePoint, BalanceSnapshot, DailyCandle, Delivery, Notification
from app.prices.valuation import round_fiat
from app.sync import demo
from app.timeutil import utcnow
from tests.conftest import H
from tests.test_discord import GOOD
from tests.test_sync import synced_wallet
from tests.wallet_helpers import hold, user_with, wallet


@pytest.fixture(autouse=True)
def fresh_demo(monkeypatch):
    monkeypatch.setattr(demo, "BALANCES", dict(demo.BALANCES))


def snap(app):
    return app.state.prices.fresh(app.state.session_factory)


def check(app) -> list[str]:
    with app.state.session_factory() as db:
        fired = sa.evaluate(db, None, snap(app))
        db.commit()
    return fired


def price(app, cid="bitcoin", fiat="usd") -> Decimal:
    return snap(app).quotes[cid][fiat].price


def add(c, kind, **params):
    r = c.post("/api/alerts", json={"kind": kind, "params": params}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def notes(app):
    with app.state.session_factory() as db:
        return [
            (n.title, n.body) for n in db.scalars(select(Notification).order_by(Notification.id))
        ]


def shown(app):
    return [(nt.render(t), nt.render(b)) for t, b in notes(app)]


# ---- portfolio -------------------------------------------------------------------------------


def test_portfolio_above_fires_once_and_rearms(logged_in, app):
    w = wallet(logged_in, "Cold")
    hold(logged_in, w["id"], "BTC", "1")
    btc = price(app)
    a = add(logged_in, "portfolio", condition="above", value=str(btc - 1), fiat="usd")
    assert a["text"] == f"Portfolio goes above {sa.plain(btc - 1)} USD"
    assert check(app) == [f"Your portfolio is above {Decimal(round_fiat(btc - 1, 'usd')):,} USD"]
    assert check(app) == []  # once
    title, body = shown(app)[-1]
    assert body == f"Now {Decimal(round_fiat(btc, 'usd')):,} USD."
    hold(logged_in, w["id"], "BTC", "0.5")  # well below: re-arms
    check(app)
    hold(logged_in, w["id"], "BTC", "1")
    assert len(check(app)) == 1


def test_portfolio_move_needs_history(logged_in, app):
    w = wallet(logged_in, "Cold")
    hold(logged_in, w["id"], "BTC", "1")
    add(logged_in, "portfolio", condition="move", value="10", window="24h")
    assert check(app) == []
    alert = logged_in.get("/api/alerts").json()["alerts"][0]
    assert alert["note"] == "not enough balance history yet"
    # A day ago it was worth half: +100 %. (The wallet existed then: history starts with it.)
    half = round_fiat(price(app) / 2, "usd")
    with app.state.session_factory() as db:
        from app.models import Wallet

        db.get(Wallet, w["id"]).created_at = utcnow() - timedelta(days=3)
        recent = BalanceSnapshot(at=utcnow() - timedelta(hours=2))  # too recent for "24 hours"
        db.add(recent)
        db.flush()
        db.add(BalancePoint(snapshot_id=recent.id, wallet_id=w["id"], symbol="BTC",
                            amount="0.5", values={"usd": half}))  # fmt: skip
        db.commit()
    assert check(app) == []  # only the value from 24+ hours ago counts
    with app.state.session_factory() as db:
        s = BalanceSnapshot(at=utcnow() - timedelta(hours=25))
        db.add(s)
        db.flush()
        db.add(BalancePoint(snapshot_id=s.id, wallet_id=w["id"], symbol="BTC", amount="0.5",
                            values={"usd": half}))  # fmt: skip
        db.commit()
    assert check(app) == ["Your portfolio moved +100.0 % in 24 hours"]


# ---- drift -----------------------------------------------------------------------------------


def test_drift_from_targets(logged_in, app):
    w = wallet(logged_in, "Cold")
    btc, eth = price(app), price(app, "ethereum")
    # Equal values: 50 / 50.
    hold(logged_in, w["id"], "BTC", "1")
    hold(logged_in, w["id"], "ETH", str((btc / eth).quantize(Decimal("0.00000001"))))
    add(logged_in, "drift", targets={"BTC": "60", "ETH": "40"}, threshold="5")
    assert check(app) == ["Your portfolio drifted from its targets"]
    _, body = notes(app)[-1]
    assert nt.render(body).startswith("BTC 50.0 % (target 60 %); ETH 50.0 % (target 40 %)")
    assert nt.render(body, set()).startswith("BTC is below its target; ETH is above its target")
    assert check(app) == []
    with app.state.session_factory() as db:  # back within the targets: re-armed
        a = db.scalar(select(Alert))
        a.params = {**a.params, "targets": {"BTC": "52", "ETH": "48"}}
        db.commit()
    check(app)
    with app.state.session_factory() as db:
        assert db.scalar(select(Alert)).armed is True


def test_drift_counts_other_coins(logged_in, app):
    w = wallet(logged_in, "Cold")
    hold(logged_in, w["id"], "BTC", "1")
    add(logged_in, "drift", targets={"BTC": "50"}, threshold="10")  # the rest: other coins, 50 %
    assert check(app) == ["Your portfolio drifted from its targets"]
    assert "other coins 0.0 % (target 50 %)" in shown(app)[-1][1]


# ---- trend -----------------------------------------------------------------------------------


def days_of(app, symbol, closes, highs=None):
    today = utcnow().date()
    with app.state.session_factory() as db:
        for c in db.scalars(select(DailyCandle).where(DailyCandle.symbol == symbol)):
            db.delete(c)
        db.flush()
        for i, close in enumerate(closes):
            day = today - timedelta(days=len(closes) - i)
            hi = (highs or closes)[i]
            db.add(DailyCandle(symbol=symbol, day=day, open=str(close), high=str(hi),
                               low=str(close), close=str(close)))  # fmt: skip
        db.commit()


def test_moving_average_cross(logged_in, app):
    btc = price(app)
    add(logged_in, "trend", symbol="btc", signal="ma_cross", days=5, direction="either")
    assert check(app) == []
    a = logged_in.get("/api/alerts").json()["alerts"][0]
    assert a["note"] == "needs 5 days of daily prices"
    days_of(app, "BTC", [btc * 2] * 5)  # average far above today's price
    assert check(app) == []  # the first look only notes the side
    assert logged_in.get("/api/alerts").json()["alerts"][0]["side"] == "below"
    days_of(app, "BTC", [btc / 2] * 5)  # now far below: crossed upwards
    assert check(app) == ["BTC crossed above its 5-day average"]
    assert check(app) == []
    days_of(app, "BTC", [btc * 2] * 5)
    assert check(app) == ["BTC crossed below its 5-day average"]  # every change of side


def test_cross_in_one_direction_only(logged_in, app):
    btc = price(app)
    add(logged_in, "trend", symbol="BTC", signal="ma_cross", days=5, direction="down")
    days_of(app, "BTC", [btc / 2] * 5)
    check(app)
    days_of(app, "BTC", [btc * 2] * 5)
    assert check(app) == ["BTC crossed below its 5-day average"]
    days_of(app, "BTC", [btc / 2] * 5)
    assert check(app) == []  # upwards: not asked for


def test_drop_from_high(logged_in, app):
    btc = price(app)
    add(logged_in, "trend", symbol="BTC", signal="drawdown", days=5, percent="20")
    days_of(app, "BTC", [btc] * 5, highs=[btc, btc * Decimal("1.5"), btc, btc, btc])
    assert check(app) == ["BTC is 33.3 % below its 5-day high"]
    assert check(app) == []
    days_of(app, "BTC", [btc] * 5)  # no drop any more: re-arms
    check(app)
    days_of(app, "BTC", [btc] * 5, highs=[btc * 2] * 5)
    assert check(app) == ["BTC is 50.0 % below its 5-day high"]


def test_todays_candle_doesnt_count(logged_in, app):
    """The average is of finished days; today's (still changing) candle isn't one."""
    btc = price(app)
    add(logged_in, "trend", symbol="BTC", signal="ma_cross", days=5)
    days_of(app, "BTC", [btc] * 4)
    with app.state.session_factory() as db:
        today = utcnow().date()
        db.add(DailyCandle(symbol="BTC", day=today, open="1", high="1", low="1", close="1"))
        db.commit()
    check(app)
    assert (
        logged_in.get("/api/alerts").json()["alerts"][0]["note"] == "needs 5 days of daily prices"
    )


# ---- wallet changes (from a real sync) -------------------------------------------------------


def sync(c, wid):
    r = c.post(f"/api/wallets/{wid}/sync", headers=H).json()
    assert r["ok"], r
    return r


def test_wallet_change_from_a_sync(logged_in, app):
    price(app)  # the server has prices (a running one always does): values can be shown
    w, _ = synced_wallet(logged_in, "Coinbase main")
    add(logged_in, "wallet", wallet_id=w["id"], direction="any")
    sync(logged_in, w["id"])
    assert notes(app) == []  # the first sync isn't news: everything "arrives"
    demo.BALANCES["ETH"] = "1.25"
    sync(logged_in, w["id"])
    title, body = shown(app)[-1]
    assert title == "Coinbase main: balance changed"
    assert body.startswith("ETH went down by 1 ETH (about ")
    assert body.endswith("If you didn't expect this, check the account now.")
    raw_title, raw_body = notes(app)[-1]
    assert nt.render(raw_title, set()) == "A synced wallet: balance changed"
    assert nt.render(raw_body, set()) == (
        "ETH went down. If you didn't expect this, check the account now."
    )


def test_an_alert_for_one_wallet_ignores_the_others(logged_in, app):
    from tests.test_sync import connect

    a, _ = synced_wallet(logged_in, "First")
    b = wallet(logged_in, "Second", kind="exchange")
    conn = connect(logged_in, key="second-key-123456789").json()
    logged_in.put(f"/api/wallets/{b['id']}/source", json={"kind": "exchange",
                  "connection_id": conn["id"]}, headers=H)  # fmt: skip
    add(logged_in, "wallet", wallet_id=b["id"])
    sync(logged_in, a["id"])
    demo.BALANCES["ETH"] = "1"
    sync(logged_in, a["id"])
    assert notes(app) == []


def test_wallet_alert_filters(logged_in, app):
    w, _ = synced_wallet(logged_in)
    add(logged_in, "wallet", direction="up")  # any synced wallet, only increases
    add(logged_in, "wallet", direction="any", min_value="1000000000", fiat="usd")
    sync(logged_in, w["id"])
    demo.BALANCES["ETH"] = "1"  # down, and small
    sync(logged_in, w["id"])
    assert notes(app) == []
    demo.BALANCES["ETH"] = "5"
    sync(logged_in, w["id"])
    assert [t for t, _ in shown(app)] == ["Demo account: balance changed"]


def test_discord_gets_only_the_allowed_details(logged_in, app):
    price(app)
    logged_in.put("/api/notifications/channels/discord", json={"url": GOOD}, headers=H)
    prefs = {"channels": {"portfolio": {"inapp": True, "discord": True}}}
    logged_in.patch("/api/me/preferences", json={"notifications": prefs}, headers=H)
    w, _ = synced_wallet(logged_in, "Coinbase main")
    add(logged_in, "wallet")
    sync(logged_in, w["id"])
    demo.BALANCES["ETH"] = "1.25"
    sync(logged_in, w["id"])
    with app.state.session_factory() as db:
        d = db.scalars(select(Delivery)).all()[-1]
        assert (d.title, d.body) == (
            "A synced wallet: balance changed",
            "ETH went down. If you didn't expect this, check the account now.",
        )
    prefs["discord_details"] = ["amounts", "wallets"]
    logged_in.patch("/api/me/preferences", json={"notifications": prefs}, headers=H)
    demo.BALANCES["ETH"] = "2.25"
    sync(logged_in, w["id"])
    with app.state.session_factory() as db:
        d = db.scalars(select(Delivery)).all()[-1]
        assert (d.title, d.body) == ("Coinbase main: balance changed", "ETH went up by 1 ETH.")
    # And the app always shows everything.
    listed = logged_in.get("/api/notifications").json()["items"][0]
    assert listed["title"] == "Coinbase main: balance changed" and "(about " in listed["body"]


def test_typed_messages_cant_make_markers(logged_in, app):
    logged_in.post(
        "/api/notifications/send",
        json={"to": "all", "title": "Hi [[values:x|y]]", "body": "b", "level": "info"},
        headers=H,
    )
    assert shown(app)[-1][0] == "Hi [values:x|y]]"


# ---- the rules -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "params", "message"),
    [
        ("portfolio", {"condition": "above", "value": "-5"}, "between"),
        ("portfolio", {"condition": "move", "value": "abc"}, "must be a number"),
        ("drift", {"targets": {"BTC": "70", "ETH": "40"}, "threshold": "5"}, "more than 100"),
        ("drift", {"targets": {"NOPE": "10"}, "threshold": "5"}, "No coin NOPE"),
        ("trend", {"symbol": "BTC", "signal": "drawdown", "days": 20}, "needs a percent"),
        ("trend", {"symbol": "BTC", "signal": "ma_cross", "days": 2}, "greater than or equal"),
        ("trend", {"symbol": "NOPE", "signal": "ma_cross", "days": 20}, "No coin"),
        ("wallet", {"wallet_id": 99999}, "doesn't sync"),
    ],
)
def test_bad_alerts_are_refused(logged_in, kind, params, message):
    r = logged_in.post("/api/alerts", json={"kind": kind, "params": params}, headers=H)
    assert r.status_code == 422 and message in r.json()["detail"], r.text


def test_who_may_have_which_alert(logged_in, app):
    prices_only = user_with(app, logged_in, "pricey", ["prices.view"])
    assert prices_only.get("/api/alerts").json()["kinds"] == ["trend"]
    r = prices_only.post(
        "/api/alerts",
        json={"kind": "portfolio", "params": {"condition": "above", "value": "1"}},
        headers=H,
    )
    assert r.status_code == 403  # holdings need wallets.view
    add(prices_only, "trend", symbol="BTC", signal="ma_cross", days=20)
    mine = add(logged_in, "trend", symbol="ETH", signal="ma_cross", days=20)
    assert len(prices_only.get("/api/alerts").json()["alerts"]) == 1  # only your own
    assert prices_only.delete(f"/api/alerts/{mine['id']}", headers=H).status_code == 404
    nobody = user_with(app, logged_in, "nobody", ["wallets.view"])
    assert nobody.get("/api/alerts").status_code == 403
    actions = [e["action"] for e in logged_in.get("/api/audit?q=alerts.").json()]
    assert actions.count("alerts.create") == 2


def test_an_alert_waits_when_its_owner_loses_access(logged_in, app):
    viewer = user_with(app, logged_in, "viewer", ["wallets.view", "prices.view"])
    w = wallet(logged_in, "Cold")
    hold(logged_in, w["id"], "BTC", "1")
    add(viewer, "portfolio", condition="above", value="1")
    vid = next(u["id"] for u in logged_in.get("/api/users").json() if u["username"] == "viewer")
    logged_in.patch(f"/api/users/{vid}", json={"permissions": ["prices.view"]}, headers=H)
    assert check(app) == []


def test_the_job_never_uses_practice_or_stale_prices(logged_in, app):
    add(logged_in, "trend", symbol="BTC", signal="ma_cross", days=5)
    logged_in.put("/api/services/features", json={"practice_prices": True}, headers=H)
    assert app.state.smart_alerts.tick() == {"skipped": "practice prices are on"}
    logged_in.put("/api/services/features", json={"practice_prices": False}, headers=H)
    app.state.prices.fresh(app.state.session_factory)
    app.state.prices.real.fail_with = "offline"
    app.state.prices.invalidate()
    assert app.state.smart_alerts.tick() == {"skipped": "prices are stale"}


def test_at_most_fifty_each(logged_in, monkeypatch):
    monkeypatch.setattr(sa, "MAX_PER_USER", 1)
    add(logged_in, "trend", symbol="BTC", signal="ma_cross", days=20)
    r = logged_in.post(
        "/api/alerts",
        json={"kind": "trend", "params": {"symbol": "BTC", "signal": "ma_cross", "days": 30}},
        headers=H,
    )
    assert r.status_code == 409
