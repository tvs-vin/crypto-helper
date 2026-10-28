"""13a: live trading foundations. Exchange switches (on: super only), trading keys (checked
with the exchange: never one that can withdraw; personal or shared), each person's cap with its
ceiling (raising needs a fresh 2FA code), permissions, audit, and the CLI's `live off`."""

import json

import pytest

from app import trading as tr
from app.models import TradingKey, User
from app.sync import TradeCheck
from app.sync.demo import Demo
from tests.conftest import PASSWORD, H
from tests.test_totp import code
from tests.test_totp import enrol as _enrol
from tests.test_users import PW2
from tests.wallet_helpers import user_with


def enrol(c, password=None):
    """2FA for this client's account (test users have PW2; super has conftest's password)."""

    me = c.get("/api/auth/me").json()
    return _enrol(c, password or (PASSWORD if me.get("is_super") else PW2))


DEMO_KEY = {"key": "demo-trader-1234", "secret": "anything"}


def switch(c, on=True, exchange="demo"):
    return c.put("/api/services/live", json={"exchange": exchange, "on": on}, headers=H)


def add(c, creds=None, **kw):
    body = {"kind": "demo", "label": "My demo", "credentials": creds or DEMO_KEY, **kw}
    return c.post("/api/trading/keys", json=body, headers=H)


@pytest.fixture
def trader(logged_in, app):
    """super (2FA on) switched demo live trading on; `trader` has live.trade and 2FA."""
    enrol(logged_in)
    assert switch(logged_in).status_code == 200
    c = user_with(app, logged_in, "trader", ["live.trade"])
    c.secret, _ = enrol(c)
    return c


# ---- switches --------------------------------------------------------------------------------


def test_only_super_switches_live_trading_on(logged_in, app):
    admin = user_with(app, logged_in, "svcadmin", ["services.manage"])
    assert switch(logged_in).json()  # super without 2FA: refused
    r = switch(logged_in)
    assert r.status_code == 403 and "two-factor" in r.json()["detail"]
    enrol(logged_in)
    assert switch(logged_in).status_code == 200
    r = switch(admin)  # an admin can't switch it on...
    assert r.status_code == 403 and "Only super" in r.json()["detail"]
    r = switch(admin, on=False)  # ...but can switch it off
    assert r.status_code == 200
    assert {x["id"]: x["on"] for x in r.json()}["demo"] is False
    actions = [e["detail"] for e in logged_in.get("/api/audit?q=services.live").json()]
    assert "live trading on Demo exchange off" in actions


# ---- trading keys ----------------------------------------------------------------------------


def test_a_key_is_checked_encrypted_and_personal(trader, logged_in, app):
    r = add(trader)
    assert r.status_code == 201, r.text
    k = r.json()
    assert k["shared"] is False and k["owner"] == "trader" and "can trade (checked)" in k["check"]
    assert "can't withdraw (checked)" in k["check"] and k["masked"].endswith("1234")
    with app.state.session_factory() as db:
        row = db.get(TradingKey, k["id"])
        assert "anything" not in row.secret_encrypted and "demo-trader" not in row.secret_encrypted
        assert json.loads(app.state.secret_box.decrypt(row.secret_encrypted)) == DEMO_KEY
    other = user_with(app, logged_in, "othertrader", ["live.trade"])
    assert other.get("/api/trading").json()["keys"] == []  # not theirs
    assert other.delete(f"/api/trading/keys/{k['id']}", headers=H).status_code == 404
    assert "secret" not in json.dumps(trader.get("/api/trading").json()).replace('secret"', "")


@pytest.mark.parametrize(
    ("key", "status", "words"),
    [
        ("withdraw-1234", 422, "can withdraw"),
        ("view-12345678", 422, "can't trade"),
        ("fail-12345678", 422, "didn't accept it"),
    ],
)
def test_keys_that_can_withdraw_or_cant_trade_are_refused(trader, key, status, words):
    r = add(trader, {"key": key, "secret": "x"})
    assert r.status_code == status and words in json.dumps(r.json()), r.text
    assert trader.get("/api/trading").json()["keys"] == []


def test_when_the_exchange_cant_say_the_person_confirms(trader):
    r = add(trader, {"key": "unknown-12345678", "secret": "x"})
    assert r.status_code == 409 and r.json()["detail"]["confirm"].startswith("I created this key")
    r = add(trader, {"key": "unknown-12345678", "secret": "x"}, confirm_no_withdrawals=True)
    assert r.status_code == 201 and "confirmed by trader" in r.json()["check"]


def test_rules_for_adding_keys(logged_in, app):
    enrol(logged_in)
    no_2fa = user_with(app, logged_in, "no2fa", ["live.trade"])
    r = add(no_2fa)
    assert r.status_code == 403 and "two-factor" in r.json()["detail"]
    trader = user_with(app, logged_in, "tradernow", ["live.trade"])
    enrol(trader)
    r = add(trader)
    assert r.status_code == 409 and "isn't switched on" in r.json()["detail"]  # off at first
    switch(logged_in)
    r = add(trader, shared=True)
    assert r.status_code == 403 and "live.keys.shared" in r.json()["detail"]
    phrase = " ".join(["zoo"] * 11 + ["wrong"])
    r = add(trader, label=phrase)
    assert r.status_code == 422 and "zoo" not in r.text
    assert add(trader, credentials={"key": "only"}).status_code == 422
    nobody = user_with(app, logged_in, "nolive", ["wallets.view"])
    assert nobody.get("/api/trading").status_code == 403


def test_shared_keys(trader, logged_in, app):
    sharer = user_with(app, logged_in, "sharer", ["live.keys.shared"])
    enrol(sharer)
    r = add(sharer, shared=True, label="Household key")
    assert r.status_code == 201 and r.json()["shared"] is True and r.json()["owner"] is None
    other = user_with(app, logged_in, "sharer2", ["live.keys.shared"])
    assert [k["label"] for k in other.get("/api/trading").json()["keys"]] == ["Household key"]
    assert trader.get("/api/trading").json()["keys"] == []  # live.trade alone: not shared keys
    with app.state.session_factory() as db:
        key = db.get(TradingKey, r.json()["id"])
        users = {u.username: u for u in db.query(User)}
        assert tr.may_use(users["sharer"], key) is False  # shared keys + live.trade to trade
        assert tr.may_see(users["sharer2"], key) and not tr.may_see(users["trader"], key)


def test_a_recheck_deletes_a_key_that_can_now_withdraw(trader, monkeypatch):
    k = add(trader).json()
    monkeypatch.setattr(Demo, "check_trading", lambda self, c: TradeCheck(True, True, None, "x"))
    r = trader.post(f"/api/trading/keys/{k['id']}/check", headers=H)
    assert r.status_code == 422 and "can withdraw" in r.json()["detail"]
    assert trader.get("/api/trading").json()["keys"] == []


def test_admins_can_delete_keys_of_people_they_manage(trader, logged_in, app):
    k = add(trader).json()
    admin = user_with(app, logged_in, "keyadmin", ["users.manage"])
    assert [x["id"] for x in admin.get("/api/trading/keys/all").json()] == [k["id"]]
    viewer = user_with(app, logged_in, "keyviewer", ["wallets.view"])
    assert viewer.get("/api/trading/keys/all").status_code == 403
    # keyadmin lacks live.trade, which trader holds: not someone it may manage.
    assert admin.delete(f"/api/trading/keys/{k['id']}/admin", headers=H).status_code == 403
    assert logged_in.delete(f"/api/trading/keys/{k['id']}/admin", headers=H).status_code == 204
    entry = logged_in.get("/api/audit?q=trading.key.delete").json()[0]
    assert "by an admin" in entry["detail"]


# ---- caps ------------------------------------------------------------------------------------


def test_the_default_cap_and_raising_your_own(logged_in, app):
    c = user_with(app, logged_in, "capper", ["live.trade", "live.cap"])
    secret, _ = enrol(c)
    assert c.get("/api/trading").json()["caps"] == {
        "cap": "150", "cap_is_default": True, "ceiling": None, "default": "150", "currency": "usd"
    }  # fmt: skip
    r = c.put("/api/trading/me/cap", json={"cap": "100"}, headers=H)  # lowering: no code
    assert r.status_code == 200 and r.json()["cap"] == "100"
    r = c.put("/api/trading/me/cap", json={"cap": "500"}, headers=H)
    assert r.status_code == 403 and "2FA code" in r.json()["detail"]
    r = c.put("/api/trading/me/cap", json={"cap": "500", "code": code(secret)}, headers=H)
    assert r.status_code == 200 and r.json()["cap"] == "500"
    for bad in ("0", "-5", "abc", "1.005"):
        assert c.put("/api/trading/me/cap", json={"cap": bad}, headers=H).status_code == 422
    assert c.put("/api/trading/me/cap", json={"cap": 50}, headers=H).status_code == 422  # a number
    no_perm = user_with(app, logged_in, "nocap", ["live.trade"])
    assert no_perm.put("/api/trading/me/cap", json={"cap": "10"}, headers=H).status_code == 403
    details = [e["detail"] for e in logged_in.get("/api/audit?q=trading.cap").json()]
    assert "own cap $150 -> $100" in details and "own cap $100 -> $500" in details


def test_admins_set_caps_and_ceilings(logged_in, app):
    secret, _ = enrol(logged_in)
    c = user_with(app, logged_in, "capped", ["live.trade", "live.cap"])
    uid = next(u["id"] for u in logged_in.get("/api/users").json() if u["username"] == "capped")

    def put(**body):
        return logged_in.put(f"/api/users/{uid}/trading", json=body, headers=H)

    # Lower cap and a new ceiling only restrict: no code needed.
    r = put(cap="100", ceiling="200")
    assert r.status_code == 200 and (r.json()["live_cap"], r.json()["live_cap_ceiling"]) == (
        "100",
        "200",
    )
    assert put(cap="100", ceiling="300").status_code == 403  # a higher ceiling is a raise
    r = put(cap="100", ceiling="300", code=code(secret, 1))
    assert r.status_code == 200 and r.json()["live_cap_ceiling"] == "300"
    assert put(cap="100", ceiling="200").status_code == 200  # back down: no code
    enrol(c)
    r = c.put("/api/trading/me/cap", json={"cap": "250", "code": "000000"}, headers=H)
    assert r.status_code == 403
    assert put(cap="100", ceiling="50").status_code == 422  # a cap above its ceiling
    r = put(cap="", ceiling="50")  # the default, under a lower ceiling: no code, cap follows
    assert r.status_code == 200 and r.json()["live_cap"] == "50"
    assert put(cap="", ceiling="").status_code == 403  # no ceiling, default 150 > 50: a raise


def test_caps_maths():
    u = User(username="x", password_hash="", live_cap=None, live_cap_ceiling=None)
    assert tr.cap_of(u) == 150 and tr.ceiling_of(u) is None
    tr.set_caps(u, None, tr.parse_cap("100"))
    assert tr.cap_of(u) == 100  # the default came down to the ceiling
    with pytest.raises(tr.TradingError):
        tr.set_own_cap(u, tr.parse_cap("101"))
    assert tr.raises(None, None) is False and tr.raises(tr.parse_cap("5"), None) is True


# ---- the command line ------------------------------------------------------------------------


def test_cli_live_off_and_status(trader, logged_in, app, capsys, monkeypatch):
    import app.cli.live as live_cli
    from app import cli

    add(trader)
    monkeypatch.setattr(live_cli, "open_db", lambda settings: (None, app.state.session_factory))
    assert cli.main(["live", "status"]) == 0
    out = capsys.readouterr().out
    assert "switched on for: demo" in out and "1 trading key(s) for demo" in out
    assert cli.main(["live", "off"]) == 0
    assert "It was on for: demo" in capsys.readouterr().out
    assert {x["id"]: x["on"] for x in logged_in.get("/api/services").json()["live"]}[
        "demo"
    ] is False
    entry = logged_in.get("/api/audit?q=services.live").json()[0]
    assert entry["username"] == "<cli>"


# ---- checking an order without trading (13b) -------------------------------------------------


def check_order(c, key_id, **body):
    return c.post(f"/api/trading/keys/{key_id}/test-order", json={"coin": "BTC", **body},
                  headers=H)  # fmt: skip


def test_an_order_is_checked_without_trading(trader, logged_in):
    from app.orders import demo

    k = add(trader).json()
    before = dict(demo.PLACED)
    r = check_order(trader, k["id"], amount="25")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True and "would take it" in out["result"]
    assert out["order"]["kind"] == "limit" and out["order"]["side"] == "buy"
    assert out["order"]["limit_price"] and out["order"]["size"]
    assert demo.PLACED == before  # nothing was placed
    small = check_order(trader, k["id"], amount="0.5").json()
    assert small["ok"] is False and "smallest order value" in small["result"]
    details = [e["detail"] for e in logged_in.get("/api/audit?q=trading.key.testorder").json()]
    assert any("buy 25 BTC" in d for d in details)


def test_an_accepted_check_shows_the_key_may_trade(trader):
    k = add(trader, {"key": "unknown-12345678", "secret": "x"}, confirm_no_withdrawals=True).json()
    assert "first tiny order" in k["check"]
    check_order(trader, k["id"])
    key = next(x for x in trader.get("/api/trading").json()["keys"] if x["id"] == k["id"])
    assert "can trade (checked)" in key["check"]


def test_checks_that_cant_run(trader, logged_in, app, monkeypatch):
    from app.orders import demo

    k = add(trader).json()
    monkeypatch.setattr(demo.DEMO_ORDERS, "can_check", False)  # like Gemini
    r = check_order(trader, k["id"])
    assert r.status_code == 409 and "first tiny order" in r.json()["detail"]
    monkeypatch.setattr(demo.DEMO_ORDERS, "can_check", True)
    assert check_order(trader, k["id"], coin="NOPE").status_code == 422
    assert check_order(trader, k["id"], amount="abc").status_code == 422
    logged_in.put("/api/services/features", json={"practice_prices": True}, headers=H)
    r = check_order(trader, k["id"])
    assert r.status_code == 409 and "Practice prices" in r.json()["detail"]
    logged_in.put("/api/services/features", json={"practice_prices": False}, headers=H)
    sharer = user_with(app, logged_in, "sharecheck", ["live.keys.shared"])
    enrol(sharer)
    shared = add(sharer, shared=True).json()
    r = check_order(sharer, shared["id"])  # shared keys, but no live.trade
    assert r.status_code == 403
