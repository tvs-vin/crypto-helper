"""11a: syncing wallets. Connections (read-only keys), linking wallets, the engine, the job.

Uses the pretend Demo exchange (no network), switched on for tests in conftest."""

import pytest
from sqlalchemy import select, text

from app.models import AuditLog, Connection, Notification, User, WalletSource
from app.sync import Check, demo
from app.sync import engine as eng
from app.timeutil import utcnow
from tests.conftest import H
from tests.wallet_helpers import hold, user_with, wallet

KEY = "demo-key-123456789"
SECRET = "demo-secret-ABCDEFGHIJKLMNOP"


@pytest.fixture(autouse=True)
def fresh_balances(monkeypatch):
    monkeypatch.setattr(demo, "BALANCES", dict(demo.BALANCES))


def connect(c, key=KEY, secret=SECRET, label="My demo", **kw):
    body = {"kind": "demo", "label": label, "credentials": {"key": key, "secret": secret}, **kw}
    return c.post("/api/connections", json=body, headers=H)


def synced_wallet(c, name="Demo account"):
    w = wallet(c, name, kind="exchange")
    conn = connect(c).json()
    r = c.put(f"/api/wallets/{w['id']}/source", json={"kind": "exchange",
              "connection_id": conn["id"]}, headers=H)  # fmt: skip
    assert r.status_code == 200, r.text
    return w, conn


def amounts(c, wid):
    return {h["symbol"]: h["amount"] for h in c.get(f"/api/wallets/{wid}").json()["holdings"]}


# ---- connections -----------------------------------------------------------------------------


def test_add_a_read_only_key(logged_in, app):
    r = connect(logged_in)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["exchange"] == "Demo exchange" and c["check_summary"] == "View only"
    assert c["masked"] == "Demo exchange key …6789"
    assert SECRET not in r.text and KEY not in r.text
    listed = logged_in.get("/api/connections").text
    assert SECRET not in listed and KEY not in listed
    with app.state.session_factory() as db:
        row = db.scalar(select(Connection))
        assert SECRET not in row.secret_encrypted and KEY not in row.secret_encrypted
        assert eng.credentials(app.state.secret_box, row) == {"key": KEY, "secret": SECRET}
    audit = logged_in.get("/api/audit?q=connection").json()
    assert audit and all(SECRET not in e["detail"] and KEY not in e["detail"] for e in audit)


def test_a_key_that_can_trade_is_refused(logged_in, app):
    r = connect(logged_in, key="trade-key-1234567")
    assert r.status_code == 422 and "can trade or move funds" in r.json()["detail"]
    assert "trade-key-1234567" not in r.text
    with app.state.session_factory() as db:
        assert db.scalar(select(Connection)) is None


def test_unknown_permissions_need_confirming(logged_in):
    r = connect(logged_in, key="unknown-key-12345")
    assert r.status_code == 409
    assert r.json()["detail"]["confirm"] == "I created this key with view permission only."
    r = connect(logged_in, key="unknown-key-12345", confirm_read_only=True)
    assert r.status_code == 201 and "confirmed view-only by super" in r.json()["check_summary"]


@pytest.mark.parametrize(
    "kw, status",
    [
        ({"kind": "nope"}, 422),
        ({"credentials": {"key": KEY}}, 422),
        ({"credentials": {"key": KEY, "secret": SECRET, "extra": "x"}}, 422),
        ({"credentials": {"key": KEY, "secret": "  "}}, 422),
        ({"label": "act add age aim air all any arm art ask bag box"}, 422),  # a seed phrase
    ],
)
def test_bad_connections(logged_in, kw, status):
    body = {"kind": "demo", "label": "x", "credentials": {"key": KEY, "secret": SECRET}, **kw}
    assert logged_in.post("/api/connections", json=body, headers=H).status_code == status


def test_needs_wallets_connect(logged_in, app):
    editor = user_with(app, logged_in, "editor", ["wallets.view", "wallets.edit"])
    assert editor.get("/api/connections").status_code == 403
    assert editor.get("/api/sync/exchanges").status_code == 403
    assert connect(editor).status_code == 403
    w = wallet(logged_in, "X", kind="exchange")
    conn = connect(logged_in).json()
    body = {"kind": "exchange", "connection_id": conn["id"]}
    assert editor.put(f"/api/wallets/{w['id']}/source", json=body, headers=H).status_code == 403
    # Connect without edit isn't enough to change a wallet either.
    linker = user_with(app, logged_in, "linker2", ["wallets.view", "wallets.connect"])
    assert linker.put(f"/api/wallets/{w['id']}/source", json=body, headers=H).status_code == 403


def test_demo_exchange_only_when_switched_on(app, logged_in, monkeypatch):
    assert [e["id"] for e in logged_in.get("/api/sync/exchanges").json()] == ["demo"]
    monkeypatch.setattr(app.state.settings, "sync_demo", False)
    assert logged_in.get("/api/sync/exchanges").json() == []
    assert connect(logged_in).status_code == 422


def test_rename_check_and_delete(logged_in):
    w, conn = synced_wallet(logged_in)
    cid = conn["id"]
    r = logged_in.patch(f"/api/connections/{cid}", json={"label": "Renamed"}, headers=H)
    assert r.json()["label"] == "Renamed" and r.json()["wallets"] == [
        {"id": w["id"], "name": w["name"]}
    ]
    assert logged_in.post(f"/api/connections/{cid}/check", headers=H).status_code == 200
    r = logged_in.delete(f"/api/connections/{cid}", headers=H)
    assert r.status_code == 409 and "switch them to manual" in r.json()["detail"]
    logged_in.put(f"/api/wallets/{w['id']}/source", json={"kind": "manual"}, headers=H)
    assert logged_in.delete(f"/api/connections/{cid}", headers=H).status_code == 204


# ---- syncing ---------------------------------------------------------------------------------


def test_sync_now_mirrors_the_account(logged_in):
    w, _ = synced_wallet(logged_in)
    r = logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()
    assert r["ok"] and r["sync"]["last_ok_at"] and r["sync"]["failures"] == 0
    assert amounts(logged_in, w["id"]) == {"BTC": "0.5", "ETH": "2.25", "USDC": "100"}
    assert r["sync"]["untracked"] == [{"asset": "ZZZ", "amount": "7"}]  # not added
    entry = logged_in.get("/api/audit?q=wallet.sync").json()[0]
    assert entry["username"] == "super" and "BTC: 0 -> 0.5" in entry["detail"]
    # Nothing changed: nothing written to the audit log.
    logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H)
    assert len(logged_in.get("/api/audit?q=wallet.sync").json()) == 1
    # Changes on the exchange, exactly (no rounding), and a coin that's gone.
    demo.BALANCES.update(ETH="2.123456789012345678")
    del demo.BALANCES["USDC"]
    logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H)
    assert amounts(logged_in, w["id"]) == {"BTC": "0.5", "ETH": "2.123456789012345678"}
    listed = next(x for x in logged_in.get("/api/wallets").json() if x["id"] == w["id"])
    assert listed["sync"]["label"] == "Demo exchange: My demo"


def test_synced_balances_change_only_by_syncing(logged_in):
    w, _ = synced_wallet(logged_in)
    logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H)
    r = logged_in.put(f"/api/wallets/{w['id']}/holdings/BTC", json={"amount": "9"}, headers=H)
    assert r.status_code == 409 and "synced" in r.json()["detail"]
    paper = wallet(logged_in, "Paper")
    hold(logged_in, paper["id"], "BTC", "1")
    body = {
        "from_wallet_id": paper["id"],
        "to_wallet_id": w["id"],
        "symbol": "BTC",
        "amount": "0.1",
    }
    r = logged_in.post("/api/transfers", json=body, headers=H)
    assert r.status_code == 409 and "synced" in r.json()["detail"]
    body |= {"from_wallet_id": w["id"], "to_wallet_id": paper["id"]}
    assert logged_in.post("/api/transfers", json=body, headers=H).status_code == 409
    # Back to manual: the balances stay and can be typed again.
    logged_in.put(f"/api/wallets/{w['id']}/source", json={"kind": "manual"}, headers=H)
    r = logged_in.put(f"/api/wallets/{w['id']}/holdings/BTC", json={"amount": "9"}, headers=H)
    assert r.status_code == 200


def test_deleting_a_synced_wallet_needs_no_moving(logged_in, app):
    w, _ = synced_wallet(logged_in)
    logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H)
    assert logged_in.delete(f"/api/wallets/{w['id']}", headers=H).status_code == 204
    with app.state.session_factory() as db:
        assert db.scalar(select(WalletSource)) is None
    entry = logged_in.get("/api/audit?q=wallet.delete").json()[0]
    assert "mirrored balances" in entry["detail"]


def test_only_exchange_wallets_sync_from_an_exchange(logged_in):
    paper = wallet(logged_in, "Paper")
    conn = connect(logged_in).json()
    body = {"kind": "exchange", "connection_id": conn["id"]}
    r = logged_in.put(f"/api/wallets/{paper['id']}/source", json=body, headers=H)
    assert r.status_code == 422
    r = logged_in.post(f"/api/wallets/{paper['id']}/sync", headers=H)
    assert r.status_code == 409


# ---- failures --------------------------------------------------------------------------------


def _set_key(app, key):
    with app.state.session_factory() as db:
        c = db.scalar(select(Connection))
        import json

        c.secret_encrypted = app.state.secret_box.encrypt(json.dumps({"key": key, "secret": "s"}))
        db.commit()


def titles(app, username):
    with app.state.session_factory() as db:
        uid = db.scalar(select(User.id).where(User.username == username))
        return [
            n.title for n in db.scalars(select(Notification).where(Notification.user_id == uid))
        ]


def test_failures_are_kept_and_told_once(logged_in, app):
    user_with(app, logged_in, "linker", ["wallets.view", "wallets.connect"])
    user_with(app, logged_in, "viewer", ["wallets.view"])
    w, _ = synced_wallet(logged_in)
    logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H)
    _set_key(app, "fail-now-123456789")
    for i in range(eng.NOTIFY_AFTER):
        r = logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()
        assert not r["ok"] and r["sync"]["failures"] == i + 1
        assert r["sync"]["last_error"] == "The demo exchange didn't answer"
        if i + 1 < eng.NOTIFY_AFTER:
            assert titles(app, "super") == []  # a hiccup or two isn't worth telling anyone
    assert titles(app, "super") == titles(app, "linker") == ["Demo account can't sync"]
    assert titles(app, "viewer") == []
    logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H)  # still failing: not again
    assert titles(app, "super") == ["Demo account can't sync"]
    assert amounts(logged_in, w["id"])["BTC"] == "0.5"  # balances stay as they were
    _set_key(app, KEY)
    assert logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()["ok"]
    assert titles(app, "super")[-1] == "Demo account syncs again"


def test_a_revoked_key_is_told_at_once(logged_in, app):
    w, _ = synced_wallet(logged_in)
    _set_key(app, "failfinal-123456789")
    logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H)
    assert titles(app, "super") == ["Demo account can't sync"]


def test_a_key_that_gained_trading_rights_stops_syncing(logged_in, app, monkeypatch):
    w, _ = synced_wallet(logged_in)
    logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H)
    monkeypatch.setattr(type(demo.DEMO), "check", lambda self, creds: Check(False, "can trade"))
    demo.BALANCES["BTC"] = "99"
    r = logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()
    assert not r["ok"] and "can trade or move funds" in r["error"]
    assert amounts(logged_in, w["id"])["BTC"] == "0.5"  # nothing read with that key
    assert titles(app, "super") == ["Demo account can't sync"]  # at once


# ---- the background job ----------------------------------------------------------------------


def test_job_syncs_what_is_due(logged_in, app):
    w, _ = synced_wallet(logged_in)
    other, _ = synced_wallet(logged_in, "Second")
    job = eng.SyncJob(app.state)
    assert job.tick() == [w["id"], other["id"]]  # never synced: both due
    assert job.tick() == []  # synced just now
    with app.state.session_factory() as db:
        src = db.get(WalletSource, w["id"])
        src.last_try_at = utcnow().replace(year=2000)
        db.commit()
    assert job.tick() == [w["id"]]
    logged_in.patch(f"/api/wallets/{other['id']}", json={"archived": True}, headers=H)
    with app.state.session_factory() as db:
        db.get(WalletSource, other["id"]).last_try_at = None
        db.commit()
    assert job.tick() == []  # archived wallets aren't synced
    r = logged_in.put("/api/sync/settings", json={"enabled": False, "interval_minutes": 30},
                      headers=H)  # fmt: skip
    assert r.status_code == 200
    with app.state.session_factory() as db:
        db.get(WalletSource, w["id"]).last_try_at = None
        db.commit()
    assert job.tick() == []  # switched off
    bad = {"enabled": True, "interval_minutes": 1}
    assert logged_in.put("/api/sync/settings", json=bad, headers=H).status_code == 422


def test_sync_holds_no_lock_while_reading_the_exchange(tmp_path, monkeypatch):
    """A file database (real locks): another connection writes while the exchange answers."""
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from tests.conftest import PASSWORD

    a = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'bot.db'}", price_provider="mock",
                            state_dir=str(tmp_path), sync_demo=True, _env_file=None))  # fmt: skip
    wrote = []
    original = type(demo.DEMO).fetch

    def slow_fetch(self, creds):
        with a.state.session_factory() as other:
            other.execute(text("PRAGMA busy_timeout=200"))
            other.execute(text("CREATE TABLE IF NOT EXISTS t_probe (x INTEGER)"))
            other.execute(text("INSERT INTO t_probe VALUES (1)"))
            other.commit()
            wrote.append(True)
        return original(self, creds)

    monkeypatch.setattr(type(demo.DEMO), "fetch", slow_fetch)
    with TestClient(a) as c:
        c.post("/api/setup", json={"token": a.state.setup_token, "password": PASSWORD}, headers=H)
        c.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
        w, _ = synced_wallet(c)
        assert c.post(f"/api/wallets/{w['id']}/sync", headers=H).json()["ok"]
        with a.state.session_factory() as db:  # due again, for the background job
            db.get(WalletSource, w["id"]).last_try_at = None
            db.commit()
        assert eng.SyncJob(a.state).tick() == [w["id"]]
    assert wrote == [True, True]


def test_audit_never_holds_the_secret(logged_in, app):
    synced_wallet(logged_in)
    with app.state.session_factory() as db:
        blob = " ".join(r.detail for r in db.scalars(select(AuditLog)))
    assert SECRET not in blob and KEY not in blob
