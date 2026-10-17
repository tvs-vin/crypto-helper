"""9d: price alerts. The API, the rules (fire once, re-arm after crossing back), the job."""

import types
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import price_alerts as pa
from app.models import Notification, PriceAlert
from app.prices.providers import Quote
from app.prices.service import Snapshot
from app.timeutil import utcnow
from tests.conftest import H
from tests.wallet_helpers import user_with


def add(c, symbol="BTC", kind="above", value="999999999999", fiat="usd"):
    return c.post("/api/price-alerts", json={"symbol": symbol, "kind": kind, "value": value,
                                             "fiat": fiat}, headers=H)  # fmt: skip


def snap(price, change=None, stale=False, coin="bitcoin", fiat="usd"):
    quote = Quote(Decimal(price), None if change is None else Decimal(change))
    return Snapshot(utcnow(), "coingecko", "", {coin: {fiat: quote}}, stale=stale)


def armed(app):
    """Start every alert armed, whatever the mock price was when it was added."""
    with app.state.session_factory() as db:
        for a in db.scalars(select(PriceAlert)):
            a.armed = True
        db.commit()


def check(app, s):
    with app.state.session_factory() as db:
        fired = pa.evaluate(db, None, s)
        db.commit()
    return fired


# ---- the API ---------------------------------------------------------------------------------


def test_add_list_delete(logged_in):
    r = add(logged_in, "btc", value="70000.50")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["symbol"] == "BTC" and a["value"] == "70000.5" and a["state"] == "armed"
    assert a["text"] == "BTC goes above 70,000.5 USD" and a["price"]
    assert [x["id"] for x in logged_in.get("/api/price-alerts").json()["alerts"]] == [a["id"]]
    entry = logged_in.get("/api/audit?limit=1").json()[0]
    assert entry["action"] == "price_alert.create" and "70,000.5" in entry["detail"]
    assert logged_in.delete(f"/api/price-alerts/{a['id']}", headers=H).status_code == 204
    assert logged_in.get("/api/price-alerts").json()["alerts"] == []


def test_already_true_waits_to_cross_back(logged_in):
    a = add(logged_in, value="1").json()  # BTC is above 1 already
    assert a["state"] == "waiting"


@pytest.mark.parametrize(
    "body, status",
    [
        ({"symbol": "NOPE"}, 422),
        ({"fiat": "xyz"}, 422),
        ({"value": "-5"}, 422),
        ({"value": "0"}, 422),
        ({"value": "1e5"}, 422),
        ({"value": 70000}, 422),  # a JSON number loses precision: text only
        ({"kind": "sideways"}, 422),
        ({"kind": "move", "value": "0.01"}, 422),
        ({"kind": "move", "value": "5000"}, 422),
    ],
)
def test_bad_alerts(logged_in, body, status):
    full = {"symbol": "BTC", "kind": "above", "value": "100", "fiat": "usd", **body}
    assert logged_in.post("/api/price-alerts", json=full, headers=H).status_code == status


def test_limit(logged_in, monkeypatch):
    monkeypatch.setattr(pa, "MAX_PER_USER", 2)
    add(logged_in)
    add(logged_in)
    assert add(logged_in).status_code == 409


def test_yours_only_and_needs_prices_view(logged_in, app):
    a = add(logged_in).json()
    bob = user_with(app, logged_in, "bob", ["prices.view"])
    assert bob.get("/api/price-alerts").json()["alerts"] == []
    assert bob.delete(f"/api/price-alerts/{a['id']}", headers=H).status_code == 404
    carl = user_with(app, logged_in, "carl", ["wallets.view"])
    assert carl.get("/api/price-alerts").status_code == 403
    assert add(carl).status_code == 403


def test_overview_off_for_someone_blocks_alerts(logged_in, app):
    bob = user_with(app, logged_in, "bob", ["prices.view"])
    bob_id = next(u["id"] for u in logged_in.get("/api/users").json() if u["username"] == "bob")
    r = logged_in.put(f"/api/apps/accounts/{bob_id}", json={"apps": ["wallets"]}, headers=H)
    assert r.status_code == 200, r.text
    assert bob.get("/api/price-alerts").status_code == 403


# ---- the rules -------------------------------------------------------------------------------


def test_above_fires_once_then_rearms_after_crossing_back(logged_in, app):
    add(logged_in, value="100")
    armed(app)
    assert check(app, snap("99")) == []
    assert check(app, snap("100")) == ["BTC is above 100 USD"]
    assert check(app, snap("101")) == []  # once
    assert check(app, snap("99.6")) == []  # hovering at the line: not re-armed yet
    assert check(app, snap("100.2")) == []
    assert check(app, snap("99.4")) == []  # back across (by 0.5 %): re-armed
    assert check(app, snap("100")) == ["BTC is above 100 USD"]
    with app.state.session_factory() as db:
        n = db.scalars(select(Notification).order_by(Notification.id)).first()
        assert n.category == "prices" and n.link == "overview"
        assert n.body.startswith("Now 100.00 USD") and "back below 99.50 USD" in n.body


def test_below(logged_in, app):
    add(logged_in, kind="below", value="50000")
    armed(app)
    assert check(app, snap("49999.99")) == ["BTC is below 50,000 USD"]
    assert check(app, snap("50100")) == []
    assert check(app, snap("50300")) == []  # re-armed
    assert check(app, snap("40000")) == ["BTC is below 50,000 USD"]


def test_move(logged_in, app):
    add(logged_in, kind="move", value="5")
    armed(app)
    assert check(app, snap("100", "4.9")) == []
    assert check(app, snap("100", "-6.25")) == ["BTC moved -6.2 % in 24 hours"]
    assert check(app, snap("100", "-4.5")) == []
    assert check(app, snap("100", "3")) == []  # re-armed (under 80 % of 5)
    assert check(app, snap("100", "5")) == ["BTC moved +5.0 % in 24 hours"]


def test_currency_and_coin_must_match(logged_in, app):
    add(logged_in, value="100", fiat="eur")
    armed(app)
    assert check(app, snap("1000", fiat="usd")) == []
    assert check(app, snap("1000", coin="ethereum", fiat="eur")) == []
    assert check(app, snap("1000", fiat="eur")) == ["BTC is above 100 EUR"]


def test_no_notification_without_prices_view(logged_in, app):
    bob = user_with(app, logged_in, "bob", ["prices.view"])
    add(bob, value="100")
    armed(app)
    bob_id = next(u["id"] for u in logged_in.get("/api/users").json() if u["username"] == "bob")
    logged_in.patch(f"/api/users/{bob_id}", json={"permissions": []}, headers=H)
    assert check(app, snap("200")) == []
    with app.state.session_factory() as db:
        assert db.scalar(select(PriceAlert)).armed is False  # it still counts as fired


def test_alerts_go_with_the_account(logged_in, app):
    bob = user_with(app, logged_in, "bob", ["prices.view"])
    add(bob)
    bob_id = next(u["id"] for u in logged_in.get("/api/users").json() if u["username"] == "bob")
    logged_in.delete(f"/api/users/{bob_id}", headers=H)
    with app.state.session_factory() as db:
        assert db.scalar(select(PriceAlert)) is None


# ---- the job ---------------------------------------------------------------------------------


class FakePrices:
    def __init__(self, s):
        self.snap, self.practice, self.calls = s, False, 0

    def fresh(self, factory):
        self.calls += 1
        return self.snap


def test_job(logged_in, app):
    prices = FakePrices(snap("200"))
    job = pa.PriceAlertJob(prices, app.state.session_factory)
    assert job.tick() == {"alerts": 0} and prices.calls == 0  # nothing to do, nothing fetched
    add(logged_in, value="100")
    with app.state.session_factory() as db:  # (added while BTC was far above: re-arm it)
        db.scalar(select(PriceAlert)).armed = True
        db.commit()
    assert job.tick() == {"fired": ["BTC is above 100 USD"]}
    assert job.tick() == {"skipped": "no new prices yet"}


def test_job_never_uses_stale_or_practice_prices(logged_in, app):
    add(logged_in, value="100")
    with app.state.session_factory() as db:
        db.scalar(select(PriceAlert)).armed = True
        db.commit()
    prices = FakePrices(snap("200", stale=True))
    job = pa.PriceAlertJob(prices, app.state.session_factory)
    assert job.tick() == {"skipped": "prices are stale"}
    prices.snap, prices.practice = snap("200"), True  # switched on mid-way
    assert job.tick() == {"skipped": "practice prices are on"}
    logged_in.put("/api/services/features", json={"practice_prices": True}, headers=H)
    prices.practice, before = False, prices.calls  # the switch alone is enough
    assert job.tick() == {"skipped": "practice prices are on"}
    assert prices.calls == before  # and nothing was fetched
    with app.state.session_factory() as db:
        assert db.scalar(select(PriceAlert)).armed is True


def test_job_with_the_real_price_service(logged_in, app):
    """End to end with the mock source: an alert set just under the current price fires."""
    price = Decimal(add(logged_in).json()["price"])
    add(logged_in, kind="below", value=str(price * 2))  # already true: waits
    with app.state.session_factory() as db:
        a = db.scalars(select(PriceAlert)).first()
        a.value = str(price - 1)
        db.commit()
    job = pa.PriceAlertJob(app.state.prices, app.state.session_factory)
    app.state.prices.invalidate()
    out = job.tick()
    assert out["fired"] == [f"BTC is above {pa.plain(price - 1)} USD"]


def test_describe_numbers():
    assert pa.plain(Decimal("70000")) == "70,000" and pa.plain(Decimal("0.50")) == "0.5"
    a = types.SimpleNamespace(symbol="ETH", kind="move", value="2.5", fiat="eur")
    assert pa.describe(a) == "ETH moves 2.5 % or more in 24 hours"
