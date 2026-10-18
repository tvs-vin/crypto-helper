"""9c: automatic notifications. Security events for the account (and admins), system health."""

import copy
import os
import time
import types
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import health
from app.agent.client import AgentUnavailable
from app.agent.server import Refused, parse_update_check
from app.models import Delivery, Notification, User
from app.selftest import SelfTest
from app.timeutil import utcnow
from tests.conftest import PASSWORD, H
from tests.test_totp import enrol
from tests.test_users import PW2, as_user, create


def titles(app, username) -> list[str]:
    with app.state.session_factory() as db:
        uid = db.scalar(select(User.id).where(User.username == username))
        rows = db.scalars(select(Notification).where(Notification.user_id == uid))
        return [n.title for n in rows]


def sign_in(app, username, password=PW2, ua="Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0", **kw):
    c = TestClient(app)
    body = {"username": username, "password": password, **kw}
    return c, c.post("/api/auth/login", json=body, headers={**H, "user-agent": ua})


# ---- security --------------------------------------------------------------------------------


def test_new_device_sign_in(logged_in, app):
    create(logged_in, "bob", [])
    sign_in(app, "bob")  # the very first sign-in isn't news
    sign_in(app, "bob")  # the same browser again isn't either
    assert titles(app, "bob") == []
    sign_in(app, "bob", ua="Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537")
    assert titles(app, "bob") == ["New sign-in to your account"]
    with app.state.session_factory() as db:
        n = db.scalar(select(Notification).where(Notification.title.startswith("New sign-in")))
        assert "Chrome on Windows from testclient" in n.body and n.level == "warning"
    entry = logged_in.get("/api/audit?q=login.ok&limit=1").json()[0]
    assert entry["detail"] == "Chrome on Windows"  # what's known next time


def test_sign_ins_from_before_9c_match_on_address(logged_in, app):
    create(logged_in, "bob", [])
    sign_in(app, "bob")
    with app.state.session_factory() as db:
        from app.models import AuditLog

        for row in db.scalars(select(AuditLog).where(AuditLog.action == "login.ok")):
            row.detail = ""  # how older sign-ins were recorded
        db.commit()
    sign_in(app, "bob", ua="Something else entirely")
    assert titles(app, "bob") == []


def test_lockout_tells_the_account_and_the_admins(logged_in, app):
    create(logged_in, "bob", [])
    create(logged_in, "carl", ["users.manage"])  # an admin
    create(logged_in, "dora", ["wallets.view"])  # not one
    for _ in range(app.state.settings.max_failed_logins):
        sign_in(app, "bob", password="wrong-wrong-wrong")
    assert titles(app, "bob") == ["Your account was locked"]
    assert titles(app, "super") == titles(app, "carl") == ["bob was locked out"]
    assert titles(app, "dora") == []
    # While locked, more attempts don't pile up more notifications.
    sign_in(app, "bob", password="wrong-wrong-wrong")
    assert titles(app, "bob") == ["Your account was locked"]


def test_password_changes(logged_in, app):
    create(logged_in, "bob", [])
    bob = as_user(app, "bob")
    r = bob.post("/api/auth/password", json={"current_password": PW2,
                 "new_password": "a-brand-new-passphrase"}, headers=H)  # fmt: skip
    assert r.status_code == 200
    assert titles(app, "bob") == ["Your password was changed"]
    bob_id = next(u["id"] for u in logged_in.get("/api/users").json() if u["username"] == "bob")
    logged_in.patch(f"/api/users/{bob_id}", json={"password": PW2 + "x"}, headers=H)
    assert titles(app, "bob")[-1] == "Your password was reset"
    with app.state.session_factory() as db:
        n = db.scalar(select(Notification).where(Notification.title == "Your password was reset"))
        assert "By super" in n.body and PW2 not in n.body


def test_twofa_off_and_recovery_code(logged_in, app):
    create(logged_in, "carl", ["users.manage"])
    secret, codes = enrol(logged_in)
    c, r = sign_in(app, "super", password=PASSWORD, totp=codes[0])
    assert r.status_code == 200
    assert "A recovery code was used" in titles(app, "super")
    with app.state.session_factory() as db:
        n = db.scalar(select(Notification).where(Notification.title.startswith("A recovery")))
        assert "9 left" in n.body and codes[0] not in n.body
    r = logged_in.post("/api/auth/totp/disable", json={"password": PASSWORD}, headers=H)
    assert r.status_code == 200
    assert titles(app, "super")[-1] == "Two-factor login was turned off"
    assert titles(app, "carl") == ["super has no two-factor login now"]
    with app.state.session_factory() as db:
        n = db.scalar(select(Notification).where(Notification.title.startswith("Two-factor")))
        assert n.level == "critical" and secret not in n.body


def test_admins_cant_mute_security_but_others_can(logged_in, app):
    create(logged_in, "bob", [])
    bob = as_user(app, "bob")
    off = {"notifications": {"channels": {"security": {"inapp": False}}}}
    bob.patch("/api/me/preferences", json=off, headers=H)
    logged_in.patch("/api/me/preferences", json=off, headers=H)
    for _ in range(app.state.settings.max_failed_logins):
        sign_in(app, "bob", password="wrong-wrong-wrong")
    assert titles(app, "bob") == [] and titles(app, "super") == ["bob was locked out"]


def test_security_alerts_go_to_discord_when_chosen(logged_in, app):
    create(logged_in, "bob", [])
    bob = as_user(app, "bob")
    url = "https://discord.com/api/webhooks/123456789012345678/" + "A" * 40
    bob.put("/api/notifications/channels/discord", json={"url": url}, headers=H)
    on = {"notifications": {"channels": {"security": {"inapp": True, "discord": True}}}}
    bob.patch("/api/me/preferences", json=on, headers=H)
    for _ in range(app.state.settings.max_failed_logins):
        sign_in(app, "bob", password="wrong-wrong-wrong")
    with app.state.session_factory() as db:
        d = db.scalar(select(Delivery))
        assert d.title == "Your account was locked" and "wrong-wrong" not in d.body


def test_cli_password_reset_tells_the_account(tmp_path, monkeypatch):
    from app import cli, migrate
    from app.db import make_engine, make_session_factory
    from app.security import hash_password
    from tests.test_cli import empty_config

    db_path = tmp_path / "bot.db"
    monkeypatch.setenv("BOT_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CRYPTO_HELPER_CONFIG", str(empty_config(tmp_path)))
    engine = make_engine(f"sqlite:///{db_path}")
    migrate.upgrade(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        db.add(User(username="bob", password_hash=hash_password(PASSWORD), permissions=[]))
        db.commit()
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("cli-chosen-passphrase\n"))
    assert cli.main(["account", "bob", "password", "--stdin"]) == 0
    with factory() as db:
        n = db.scalar(select(Notification))
        assert n.title == "Your password was reset" and "command line" in n.body
    engine.dispose()


# ---- system health ---------------------------------------------------------------------------

GB = 1024**3


class FakeAgent:
    def __init__(self):
        self.up = True
        self.calls: list[str] = []
        self.services = {
            "web": {"active": "active", "enabled": "enabled", "restarts": 0},
            "embed": {"active": "inactive", "enabled": "disabled", "configured": False,
                      "restarts": 0},
            "backups": {"active": "active", "enabled": "enabled", "last_result": "success"},
            "agent": {"active": "active", "enabled": "enabled"},
        }  # fmt: skip
        self.update = {"available": False, "commits": 0, "newest": None}

    def __call__(self, op, timeout=10):
        self.calls.append(op)
        if not self.up:
            raise AgentUnavailable("no socket")
        return {"services": copy.deepcopy(self.services)} if op == "status" else dict(self.update)


@pytest.fixture
def watch(app, logged_in, tmp_path):
    """A watcher on the test database with a fake agent, disk and self-test."""
    settings = app.state.settings.model_copy(update={"state_dir": str(tmp_path)})
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "bot-fresh.db").write_bytes(b"x")
    agent = FakeAgent()
    disk = types.SimpleNamespace(total=100 * GB, free=50 * GB)
    w = health.HealthWatcher(settings, app.state.session_factory, app.state.prices,
                             SelfTest(tmp_path), agent=agent, disk=lambda path: disk)  # fmt: skip
    w.fake_agent, w.fake_disk, w.dir = agent, disk, tmp_path
    return w


def test_all_well_says_nothing(watch, app):
    assert watch.tick() == [] and watch.tick() == []
    assert titles(app, "super") == []


def test_disk_low_once_then_fixed(watch, app):
    watch.fake_disk.free = int(0.5 * GB)
    assert watch.tick() == ["The disk is getting full"]
    assert watch.tick() == []  # not again while it stays low
    watch.fake_disk.free = 40 * GB
    assert watch.tick() == ["There's enough disk space again"]
    watch.fake_disk.free = 100 * 1024**2
    watch.tick()
    with app.state.session_factory() as db:
        last = db.scalars(select(Notification).order_by(Notification.id.desc())).first()
        assert last.level == "critical" and last.category == "system" and last.link == "services"


def test_who_hears_about_it(watch, app, logged_in):
    create(logged_in, "ops", ["services.manage"])
    create(logged_in, "bob", ["wallets.view"])
    watch.fake_disk.free = int(0.5 * GB)
    watch.tick()
    assert titles(app, "super") == titles(app, "ops") == ["The disk is getting full"]
    assert titles(app, "bob") == []


def test_a_restart_doesnt_repeat_it(watch, app):
    watch.fake_disk.free = int(0.5 * GB)
    watch.tick()
    again = health.HealthWatcher(watch.settings, app.state.session_factory, app.state.prices,
                                 watch.selftest, agent=watch.agent, disk=watch.disk)  # fmt: skip
    assert again.tick() == []


def test_backups(watch):
    watch.fake_agent.services["backups"]["last_result"] = "exit-code"
    assert watch.tick() == ["The last backup failed"]
    watch.fake_agent.services["backups"]["last_result"] = "success"
    assert watch.tick() == ["Backups work again"]
    old = time.time() - 3 * 24 * 3600
    os.utime(watch.dir / "backups" / "bot-fresh.db", (old, old))
    assert watch.tick() == ["Backups are overdue"]
    watch.fake_agent.services["backups"]["enabled"] = "disabled"  # switched off on purpose
    assert watch.tick() == []


def test_crashes_and_the_embed_server(watch):
    watch.tick()  # remembers the counters
    watch.fake_agent.services["web"]["restarts"] = 2
    assert watch.tick() == ["The web app crashed and was restarted"]
    assert watch.tick() == []
    watch.fake_agent.services["embed"].update(configured=True, active="failed")
    assert watch.tick() == ["The embed server stopped"]
    watch.fake_agent.services["embed"]["active"] = "active"
    assert watch.tick() == ["The embed server is running again"]


def test_agent_going_away(watch):
    watch.fake_agent.up = False
    assert watch.tick() == []  # never seen working (e.g. not installed): nothing to report
    watch.fake_agent.up = True
    watch.tick()
    watch.fake_agent.up = False
    assert watch.tick() == ["The agent isn't answering"]
    watch.fake_agent.up = True
    assert watch.tick() == ["The agent is back"]


def test_updates_are_checked_a_few_times_a_day(watch, monkeypatch):
    watch.fake_agent.update = {"available": True, "commits": 3, "newest": "abc1234 Fix things"}
    assert watch.tick() == ["An update is available"]
    watch.tick()
    assert watch.fake_agent.calls.count("update.check") == 1
    monkeypatch.setattr(health, "UPDATE_EVERY", 0)
    watch.fake_agent.update = {"available": False, "commits": 0, "newest": None}
    assert watch.tick() == []  # installed: nothing to say about it
    assert watch.fake_agent.calls.count("update.check") == 2


def test_failed_self_test_once_per_run(watch):
    import json

    run = {"finished_at": "2026-10-17T10:00:00", "ok": False, "checks": 40, "failed": 2}
    (watch.dir / "selftest.json").write_text(json.dumps(run))
    assert watch.tick() == ["The self-test failed"]
    assert watch.tick() == []
    run["finished_at"] = "2026-10-17T11:00:00"
    (watch.dir / "selftest.json").write_text(json.dumps({**run, "ok": True, "failed": 0}))
    assert watch.tick() == []


def test_prices_not_updating(watch, app):
    from app.prices.service import Snapshot

    snap = Snapshot(utcnow() - timedelta(hours=2), "coingecko", "", {}, stale=True)
    watch.prices = types.SimpleNamespace(last_snapshot=snap, last_error="CoinGecko answered 429")
    assert watch.tick() == ["Prices aren't updating"]
    with app.state.session_factory() as db:
        n = db.scalar(select(Notification).where(Notification.title.startswith("Prices")))
        assert "120 minutes" in n.body and "429" in n.body
    watch.prices = types.SimpleNamespace(
        last_snapshot=Snapshot(utcnow(), "coingecko", "", {}), last_error=None
    )
    assert watch.tick() == ["Prices are updating again"]


def test_practice_prices_never_count_as_stale(watch, logged_in):
    from app.prices.service import Snapshot

    logged_in.put("/api/services/features", json={"practice_prices": True}, headers=H)
    snap = Snapshot(utcnow() - timedelta(hours=2), "mock", "", {}, stale=True)
    watch.prices = types.SimpleNamespace(last_snapshot=snap, last_error="x")
    assert watch.tick() == []


# ---- the agent's side ------------------------------------------------------------------------


def test_parse_update_check():
    assert parse_update_check(0, "==> Checking\nAlready up to date (abc1234).\n") == {
        "available": False, "commits": 0, "newest": None}  # fmt: skip
    out = "==> Checking for updates on dev\nabc1234 Newest\ndef5678 Older\n\nRun `sudo …`\n"
    assert parse_update_check(0, out) == {
        "available": True, "commits": 2, "newest": "abc1234 Newest"}  # fmt: skip
    with pytest.raises(Refused, match="Could not resolve host"):
        parse_update_check(1, "==> Checking\nfatal: Could not resolve host: github.com\n")
