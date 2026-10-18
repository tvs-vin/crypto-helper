"""9a: notifications. Storing, reading, sending, preferences, limits, and the live stream."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import notifications as nt
from app.models import Notification, User
from tests.conftest import H
from tests.wallet_helpers import user_with


def send(c, to, title="Hello", **kw):
    return c.post("/api/notifications/send", json={"to": to, "title": title, **kw}, headers=H)


def items(c, **q):
    return c.get("/api/notifications", params=q).json()


def uid(admin, name):
    return next(u["id"] for u in admin.get("/api/users").json() if u["username"] == name)


# ---- reading ---------------------------------------------------------------------------------


def test_read_mark_and_clear(logged_in, app):
    bob = user_with(app, logged_in, "bob", ["wallets.view"])
    for i in range(3):
        assert send(logged_in, uid(logged_in, "bob"), f"n{i}", body="text").status_code == 201
    data = items(bob)
    assert data["unread"] == 3 and [n["title"] for n in data["items"]] == ["n2", "n1", "n0"]
    first = data["items"][0]
    assert first["category"] == "messages" and first["sender"] == "super" and not first["read"]
    r = bob.post("/api/notifications/read", json={"ids": [first["id"]]}, headers=H)
    assert r.json()["unread"] == 2
    assert len(items(bob, unread=True)["items"]) == 2
    assert bob.post("/api/notifications/read", json={}, headers=H).json()["unread"] == 0
    assert bob.delete("/api/notifications", headers=H).status_code == 204  # clear read
    assert items(bob)["items"] == []


def test_only_your_own(logged_in, app):
    bob = user_with(app, logged_in, "bob", [])
    carl = user_with(app, logged_in, "carl", [])
    send(logged_in, uid(logged_in, "bob"))
    n = items(bob)["items"][0]
    assert items(carl)["items"] == []
    assert carl.delete(f"/api/notifications/{n['id']}", headers=H).status_code == 404
    carl.post("/api/notifications/read", json={"ids": [n["id"]]}, headers=H)
    assert items(bob)["unread"] == 1  # carl couldn't mark bob's
    assert TestClient(app).get("/api/notifications").status_code == 401


# ---- sending ---------------------------------------------------------------------------------


def test_sending_needs_the_permission_and_is_audited(logged_in, app):
    bob = user_with(app, logged_in, "bob", [])
    assert send(bob, "all").status_code == 403
    assert bob.get("/api/notifications/recipients").status_code == 403
    r = send(logged_in, "all", "Maintenance tonight", level="warning", link="services")
    assert r.status_code == 201 and r.json() == {"sent": 2, "to": "everyone"}
    n = items(bob)["items"][0]
    assert n["level"] == "warning" and n["link"] == "services"
    entry = logged_in.get("/api/audit?limit=1").json()[0]
    assert entry["action"] == "notifications.send" and "to everyone" in entry["detail"]


@pytest.mark.parametrize(
    "kw, status",
    [
        ({"to": 99999}, 404),
        ({"to": "nobody"}, 404),
        ({"to": "all", "link": "not-a-window"}, 422),
        ({"to": "all", "level": "panic"}, 422),
        ({"to": "all", "title": ""}, 422),
        ({"to": "all", "title": "x" * 121}, 422),
        ({"to": "all", "body": "abandon " * 11 + "about"}, 422),  # a pasted recovery phrase
    ],
)
def test_bad_sends(logged_in, kw, status):
    body = {"title": "Hello", **kw}
    r = logged_in.post("/api/notifications/send", json=body, headers=H)
    assert r.status_code == status, r.text


# ---- preferences -----------------------------------------------------------------------------


def test_people_choose_what_they_get(logged_in, app):
    bob = user_with(app, logged_in, "bob", [])
    off = {"notifications": {"channels": {"messages": {"inapp": False}}}}
    assert bob.patch("/api/me/preferences", json=off, headers=H).status_code == 200
    assert send(logged_in, uid(logged_in, "bob")).json()["sent"] == 0
    assert items(bob)["items"] == []


def test_admins_always_get_security(app, logged_in):
    with app.state.session_factory() as db:
        sup = db.scalar(__import__("sqlalchemy").select(User).where(User.is_super.is_(True)))
        sup.preferences = {"notifications": {"channels": {"security": {"inapp": False}}}}
        assert nt.wants(sup, "security")
        assert not nt.wants(
            User(is_super=False, permissions=[], preferences=sup.preferences), "security"
        )


# ---- limits ----------------------------------------------------------------------------------


def test_each_person_keeps_at_most_the_newest(logged_in, app, monkeypatch):
    monkeypatch.setattr(nt, "KEEP_PER_USER", 3)
    bob = user_with(app, logged_in, "bob", [])
    for i in range(5):
        send(logged_in, uid(logged_in, "bob"), f"n{i}")
    assert [n["title"] for n in items(bob)["items"]] == ["n4", "n3", "n2"]


def test_old_ones_are_swept(app, logged_in):
    from datetime import timedelta

    from app.timeutil import utcnow

    send(logged_in, "all", "old")
    with app.state.session_factory() as db:
        for n in db.query(Notification):
            n.created_at = utcnow() - timedelta(days=nt.KEEP_DAYS + 1)
        db.commit()
        assert nt.sweep(db) >= 1
        db.commit()
    assert items(logged_in)["items"] == []


# ---- announced only after commit -------------------------------------------------------------


class FakeHub(nt.Hub):
    def __init__(self):
        super().__init__()
        self.sent = []

    def publish(self, user_id, event_name, data):
        self.sent.append((user_id, data["title"]))


def test_live_push_happens_after_commit_and_not_on_rollback(app, logged_in):
    hub = FakeHub()
    with app.state.session_factory() as db:
        users = nt.everyone(db)
        nt.notify(db, hub, users, category="messages", title="kept")
        assert hub.sent == []  # not before commit
        db.commit()
        assert [t for _, t in hub.sent] == ["kept"]
        nt.notify(db, hub, users, category="messages", title="rolled back")
        db.rollback()
        db.commit()
        assert [t for _, t in hub.sent] == ["kept"]


# ---- the live stream (a real server: the test client can't hold an endless stream open) ------


@pytest.fixture(scope="module")
def live():
    from tests.ui.conftest import Server
    from toolchain.tester.server import SpawnedServer

    s = SpawnedServer()
    s.start()
    srv = Server(s)
    srv.api("POST", "/api/setup", {"token": s.setup_token, "password": s.password})
    srv.make_user("streamer", [])
    yield srv
    s.stop()


def _login(srv, name, password):
    _, headers, _ = srv.api("POST", "/api/auth/login", {"username": name, "password": password})
    return headers["set-cookie"].split(";")[0]


def _open(srv, cookie):
    import urllib.request

    req = urllib.request.Request(
        srv.base_url + "/api/notifications/stream", headers={"Cookie": cookie}
    )
    return urllib.request.urlopen(req, timeout=10)


def _next_event(resp, timeout=10):
    """The next named event (skips keep-alives)."""
    name, deadline = None, time.time() + timeout
    while time.time() < deadline:
        line = resp.readline().decode().rstrip("\n")
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            return name, json.loads(line[6:])
    return None


def test_stream_delivers_new_notifications_live(live):
    cookie = _login(live, "streamer", "ui-test-passphrase")
    admin = live.admin_cookie()
    with _open(live, cookie) as resp:
        assert resp.status == 200 and resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-store"
        users = live.api("GET", "/api/users", cookie=admin)[2]
        sid = next(u["id"] for u in users if u["username"] == "streamer")
        time.sleep(0.3)
        live.api(
            "POST", "/api/notifications/send", {"to": sid, "title": "Live one", "body": "hi"}, admin
        )
        name, data = _next_event(resp)
    assert name == "notification" and data["title"] == "Live one" and data["body"] == "hi"


def test_stream_needs_a_session(live):
    import urllib.error

    with pytest.raises(urllib.error.HTTPError) as e:
        _open(live, "session=made-up")
    assert e.value.code == 401


def test_a_stream_only_hears_its_own_user(live):
    admin = live.admin_cookie()
    cookie = _login(live, "streamer", "ui-test-passphrase")
    with _open(live, cookie) as resp:
        time.sleep(0.3)
        users = live.api("GET", "/api/users", cookie=admin)[2]
        super_id = next(u["id"] for u in users if u["username"] == "super")
        sid = next(u["id"] for u in users if u["username"] == "streamer")
        live.api("POST", "/api/notifications/send", {"to": super_id, "title": "Not yours"}, admin)
        live.api("POST", "/api/notifications/send", {"to": sid, "title": "Yours"}, admin)
        name, data = _next_event(resp)
    assert data["title"] == "Yours"


def test_stream_ends_when_the_session_does(app, logged_in, monkeypatch):
    """The generator itself, with a short re-check: signing out ends the stream."""
    import asyncio
    import types

    from app.deps import SESSION_COOKIE
    from app.routers import notifications as router

    monkeypatch.setattr(router, "RECHECK_SECONDS", 0)
    monkeypatch.setattr(router, "HEARTBEAT_SECONDS", 0.05)
    token = logged_in.cookies.get(SESSION_COOKIE)

    async def disconnected():
        return False

    async def run(cookie):
        request = types.SimpleNamespace(app=app, cookies={SESSION_COOKIE: cookie},
                                        is_disconnected=disconnected)  # fmt: skip
        resp = await router.stream(request)
        out = []
        async for chunk in resp.body_iterator:
            out.append(chunk)
            if len(out) == 2:
                logged_in.post("/api/auth/logout", headers=H)  # (runs in this thread)
            if "signed-out" in chunk or len(out) > 50:
                break
        return out

    chunks = asyncio.run(asyncio.wait_for(run(token), timeout=10))
    assert any("event: signed-out" in c for c in chunks)
