"""9b: Discord webhooks. Address checks, sending (against a local fake), the outbox, quiet hours."""

import http.server
import json
import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app import discord
from app import notifications as nt
from app.models import Delivery, Notification, NotificationChannel, User
from app.timeutil import utcnow
from tests.conftest import H
from tests.wallet_helpers import user_with

GOOD = (
    "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcd"
)


# ---- addresses -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        GOOD,
        GOOD.replace("discord.com", "discordapp.com"),
        GOOD.replace("discord.com", "ptb.discord.com"),
    ],
)
def test_real_webhook_addresses_pass(url):
    assert discord.check(f"  {url} ") == url


@pytest.mark.parametrize(
    "url",
    [
        GOOD.replace("https://", "http://"),
        GOOD.replace("discord.com", "discord.com.evil.example"),
        GOOD.replace("https://discord.com", "https://discord.com@evil.example"),
        GOOD.replace("discord.com", "evil.example"),
        GOOD + "?wait=true",
        GOOD + "/../../x",
        "https://discord.com/api/webhooks/123/short",
        "https://discord.com/channels/1/2",
        "",
    ],
)
def test_anything_else_is_refused(url):
    with pytest.raises(ValueError, match="isn't a Discord webhook"):
        discord.check(url)


def test_mask_never_shows_the_token():
    token = GOOD.rsplit("/", 1)[1]
    label = discord.mask(GOOD)
    assert token not in label and token[:-4] not in label and "…5678" in label


def test_payload_never_pings_anyone():
    p = discord.payload("messages", "critical", "@everyone hello", "body")
    assert (
        p["allowed_mentions"] == {"parse": []}
        and p["embeds"][0]["color"] == discord.COLORS["critical"]
    )


# ---- sending (a local fake Discord) ----------------------------------------------------------


@pytest.fixture
def fake():
    calls = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append((self.path, json.loads(body)))
            status, payload, extra = fake.answer
            self.send_response(status)
            for k, v in extra.items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake.url = f"http://127.0.0.1:{srv.server_port}/api/webhooks/1/x"
    fake.calls = calls
    fake.answer = (204, {}, {})
    yield fake
    srv.shutdown()


def test_post_ok(fake):
    discord.post(fake.url, discord.payload("system", "info", "Hi", "there"))
    assert fake.calls[0][1]["embeds"][0]["title"] == "Hi"


@pytest.mark.parametrize(
    "answer, retry_after, final",
    [
        ((429, {"retry_after": 2.5}, {}), 2.5, False),
        ((404, {"message": "Unknown Webhook"}, {}), None, True),
        ((401, {"message": "Invalid Webhook Token"}, {}), None, True),
        ((500, {}, {}), None, False),
        ((302, {}, {"Location": "http://127.0.0.1:1/elsewhere"}), None, False),  # not followed
    ],
)
def test_post_failures(fake, answer, retry_after, final):
    fake.answer = answer
    with pytest.raises(discord.WebhookError) as e:
        discord.post(fake.url, discord.payload("system", "info", "Hi", ""))
    assert e.value.retry_after == retry_after and e.value.final == final
    assert "x" not in str(e.value).split()  # no address in the message


def test_unreachable():
    with pytest.raises(discord.WebhookError, match="Couldn't reach"):
        discord.post("http://127.0.0.1:1/api/webhooks/1/x", {})


# ---- the API ---------------------------------------------------------------------------------


class Recorder:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    def __call__(self, url, data):
        if self.error:
            raise self.error
        self.sent.append((url, data))


def test_set_test_and_remove_a_webhook(logged_in, app):
    rec = Recorder()
    app.state.delivery.poster = rec
    assert logged_in.get("/api/notifications/channels").json() == {"discord": None}
    r = logged_in.put(
        "/api/notifications/channels/discord", json={"url": "https://evil.example/x"}, headers=H
    )
    assert r.status_code == 422
    r = logged_in.put("/api/notifications/channels/discord", json={"url": GOOD}, headers=H)
    assert r.status_code == 200
    token = GOOD.rsplit("/", 1)[1]
    assert token not in r.text and token not in logged_in.get("/api/notifications/channels").text
    with app.state.session_factory() as db:
        ch = db.scalar(select(NotificationChannel))
        assert token not in ch.secret_encrypted  # encrypted at rest
        assert app.state.secret_box.decrypt(ch.secret_encrypted) == GOOD
    assert all(token not in e["detail"] for e in logged_in.get("/api/audit?limit=5").json())
    r = logged_in.post("/api/notifications/channels/discord/test", headers=H)
    assert r.status_code == 200 and rec.sent[0][0] == GOOD and r.json()["last_ok_at"]
    app.state.delivery.poster = Recorder(
        discord.WebhookError("Discord refused the webhook (404)", final=True)
    )
    r = logged_in.post("/api/notifications/channels/discord/test", headers=H)
    assert r.status_code == 502 and "404" in r.json()["detail"]
    assert logged_in.delete("/api/notifications/channels/discord", headers=H).status_code == 204
    assert logged_in.get("/api/notifications/channels").json() == {"discord": None}


# ---- the outbox ------------------------------------------------------------------------------


def _bob_with_discord(app, admin, **prefs):
    bob = user_with(app, admin, "bob", [])
    channels = {"messages": {"inapp": True, "discord": True}, **prefs.pop("channels", {})}
    bob.patch(
        "/api/me/preferences", json={"notifications": {"channels": channels, **prefs}}, headers=H
    )
    bob.put("/api/notifications/channels/discord", json={"url": GOOD}, headers=H)
    return bob


def _send_to_bob(app, title="Hello", level="info"):
    with app.state.session_factory() as db:
        bob = db.scalar(select(User).where(User.username == "bob"))
        nt.notify(db, None, [bob], category="messages", title=title, body="text", level=level)
        db.commit()


def test_outbox_delivers_and_records(logged_in, app):
    _bob_with_discord(app, logged_in)
    _send_to_bob(app)
    rec = Recorder()
    app.state.delivery.poster = rec
    assert app.state.delivery.tick() == 1
    assert rec.sent[0][1]["embeds"][0]["title"] == "Hello"
    with app.state.session_factory() as db:
        assert db.scalar(select(Delivery)).status == "sent"
        assert db.scalar(select(NotificationChannel)).last_ok_at is not None
    assert app.state.delivery.tick() == 0  # nothing twice


def test_discord_only_still_delivers_without_an_app_notification(logged_in, app):
    _bob_with_discord(app, logged_in, channels={"messages": {"inapp": False, "discord": True}})
    _send_to_bob(app)
    with app.state.session_factory() as db:
        assert db.scalar(select(Notification)) is None and db.scalar(select(Delivery)) is not None


def test_retry_then_give_up(logged_in, app):
    _bob_with_discord(app, logged_in)
    _send_to_bob(app)
    app.state.delivery.poster = Recorder(discord.WebhookError("Discord answered 500"))
    app.state.delivery.tick()
    with app.state.session_factory() as db:
        d = db.scalar(select(Delivery))
        assert d.status == "pending" and d.attempts == 1 and d.next_attempt_at > utcnow()
        for _ in range(nt.MAX_ATTEMPTS):
            d.next_attempt_at = utcnow() - timedelta(seconds=1)
            db.commit()
            app.state.delivery.tick()
            db.refresh(d)
        assert d.status == "failed" and d.attempts == nt.MAX_ATTEMPTS
        assert db.scalar(select(NotificationChannel)).last_error == "Discord answered 500"


def test_a_deleted_webhook_fails_at_once(logged_in, app):
    _bob_with_discord(app, logged_in)
    _send_to_bob(app)
    app.state.delivery.poster = Recorder(discord.WebhookError("gone (404)", final=True))
    app.state.delivery.tick()
    with app.state.session_factory() as db:
        assert db.scalar(select(Delivery)).status == "failed"


def test_rate_limit_waits_as_asked(logged_in, app):
    _bob_with_discord(app, logged_in)
    _send_to_bob(app, "one")
    _send_to_bob(app, "two")
    app.state.delivery.poster = Recorder(discord.WebhookError("slow down", retry_after=30))
    app.state.delivery.tick()
    with app.state.session_factory() as db:
        ds = db.scalars(select(Delivery).order_by(Delivery.id)).all()
        assert ds[0].next_attempt_at > utcnow() + timedelta(seconds=25)
        assert ds[1].attempts == 0  # stopped this round instead of hammering on


# ---- quiet hours -----------------------------------------------------------------------------


def _user(prefs):
    return User(preferences={"notifications": prefs}, is_super=False, permissions=[])


@pytest.mark.parametrize(
    "start, end, now, expect_wait_min",
    [
        ("22:00", "07:00", "23:30", 450),  # across midnight
        ("22:00", "07:00", "06:00", 60),
        ("22:00", "07:00", "12:00", None),
        ("09:00", "17:00", "10:15", 405),
        ("09:00", "17:00", "17:00", None),
    ],
)
def test_quiet_hours(start, end, now, expect_wait_min):
    u = _user({"quiet_from": start, "quiet_to": end, "utc_offset_minutes": 0})
    t = datetime(2026, 10, 17, int(now[:2]), int(now[3:]))
    until = nt.quiet_until(u, "info", t)
    if expect_wait_min is None:
        assert until is None
    else:
        assert until - t == timedelta(minutes=expect_wait_min)
    assert nt.quiet_until(u, "critical", t) is None  # critical isn't held back


def test_quiet_hours_use_the_persons_time_zone():
    u = _user({"quiet_from": "22:00", "quiet_to": "07:00", "utc_offset_minutes": -240})  # UTC-4
    t = datetime(2026, 10, 17, 3, 0)  # 23:00 local
    assert nt.quiet_until(u, "info", t) == datetime(2026, 10, 17, 11, 0)  # 07:00 local
