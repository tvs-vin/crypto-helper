from datetime import timedelta

from sqlalchemy import select

from app.models import AuditLog, Session, User
from app.timeutil import utcnow
from tests.conftest import PASSWORD, H


def login(client, username="super", password=PASSWORD):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}, headers=H
    )


def actions(app):
    with app.state.session_factory() as db:
        return [r.action for r in db.scalars(select(AuditLog).order_by(AuditLog.id))]


def test_login_ok_sets_secure_cookie_attributes(ready):
    r = login(ready)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "secure" not in cookie.replace("samesite", "")  # off by default for local http


def test_cookie_secure_flag_when_configured():
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(database_url="sqlite://", cookie_secure=True, _env_file=None))
    with TestClient(app) as c:
        c.post("/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H)
        r = login(c)
    assert "secure" in r.headers["set-cookie"].lower().replace("samesite", "")


def test_only_token_hash_is_stored(ready, app):
    r = login(ready)
    token = r.cookies.get("session")
    with app.state.session_factory() as db:
        sess = db.scalar(select(Session))
    assert sess.token_hash != token and len(sess.token_hash) == 64


def test_wrong_password_and_unknown_user_look_identical(ready):
    a = login(ready, password="wrong-password-123")
    b = login(ready, username="ghost")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_failed_logins_are_audited_and_never_log_the_password(ready, app):
    login(ready, password="wrong-password-123")
    login(ready, username="ghost")
    with app.state.session_factory() as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.action == "login.fail")).all()
    assert len(rows) == 2
    assert all("wrong-password-123" not in (r.detail or "") for r in rows)


def test_malformed_username_is_not_written_to_audit(ready, app):
    login(ready, username="My Secret Passw0rd!!")
    with app.state.session_factory() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "login.fail"))
    assert row.username == "<invalid>"


def test_lockout_after_five_failures_even_with_correct_password(ready, app):
    for _ in range(5):
        assert login(ready, password="wrong-password-123").status_code == 401
    assert "login.lockout" in actions(app)
    # Locked: the right password is refused, with the same generic answer.
    r = login(ready)
    assert r.status_code == 401 and r.json()["detail"] == "Invalid username or password"


def test_lockout_expires(ready, app):
    for _ in range(5):
        login(ready, password="wrong-password-123")
    with app.state.session_factory() as db:
        user = db.scalar(select(User))
        user.locked_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert login(ready).status_code == 200


def test_successful_login_resets_failure_counter(ready, app):
    for _ in range(4):
        login(ready, password="wrong-password-123")
    assert login(ready).status_code == 200
    for _ in range(4):
        login(ready, password="wrong-password-123")
    assert login(ready).status_code == 200  # 4 + 4 non-consecutive failures: not locked


def test_inactive_user_cannot_login(ready, app):
    with app.state.session_factory() as db:
        db.scalar(select(User)).is_active = False
        db.commit()
    assert login(ready).status_code == 401


def test_me_requires_session(ready):
    assert ready.get("/api/auth/me").status_code == 401


def test_me_for_super_lists_every_permission(logged_in):
    from app.permissions import ALL_PERMISSIONS

    data = logged_in.get("/api/auth/me").json()
    assert data["username"] == "super" and data["is_super"] is True
    assert set(data["permissions"]) == set(ALL_PERMISSIONS)
    text = str(data).lower().replace("must_change_password", "")  # a yes/no rule, not a secret
    assert "password" not in text.replace("password_", "")


def test_logout_deletes_session_and_cookie_stops_working(logged_in, app):
    assert logged_in.post("/api/auth/logout", headers=H).status_code == 200
    with app.state.session_factory() as db:
        assert db.scalar(select(Session)) is None
    assert logged_in.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected_and_removed(logged_in, app):
    with app.state.session_factory() as db:
        db.scalar(select(Session)).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert logged_in.get("/api/auth/me").status_code == 401
    with app.state.session_factory() as db:
        assert db.scalar(select(Session)) is None


def test_session_lasts_twelve_hours(logged_in, app):
    with app.state.session_factory() as db:
        sess = db.scalar(select(Session))
    delta = sess.expires_at - sess.created_at
    assert timedelta(hours=11, minutes=59) < delta <= timedelta(hours=12, seconds=5)


def test_forged_cookie_is_rejected(ready):
    ready.cookies.set("session", "not-a-real-token")
    assert ready.get("/api/auth/me").status_code == 401


def test_change_password_revokes_other_sessions(logged_in, app):
    from fastapi.testclient import TestClient

    other = TestClient(app)  # no `with`: skip lifespan so we don't dispose the shared test DB
    assert login(other).status_code == 200
    assert other.get("/api/auth/me").status_code == 200
    r = logged_in.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-passphrase"},
        headers=H,
    )
    assert r.status_code == 200
    assert logged_in.get("/api/auth/me").status_code == 200  # current session survives
    assert other.get("/api/auth/me").status_code == 401  # others are revoked
    assert login(logged_in, password="a-brand-new-passphrase").status_code == 200
    assert login(logged_in).status_code == 401  # old password no longer works


def test_change_password_rejects_wrong_current_and_short_new(logged_in):
    bad = logged_in.post(
        "/api/auth/password",
        json={"current_password": "nope-nope-nope-1", "new_password": "a-brand-new-passphrase"},
        headers=H,
    )
    assert bad.status_code == 403
    short = logged_in.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=H,
    )
    assert short.status_code == 422


def test_change_password_requires_session(ready):
    r = ready.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-passphrase"},
        headers=H,
    )
    assert r.status_code == 401


def test_wrong_current_password_counts_toward_lockout(logged_in, app):
    for _ in range(5):
        logged_in.post(
            "/api/auth/password",
            json={"current_password": "nope-nope-nope-1", "new_password": "a-brand-new-passphrase"},
            headers=H,
        )
    assert "login.lockout" in actions(app)


def test_audit_trail_for_auth_events(logged_in, app):
    logged_in.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-passphrase"},
        headers=H,
    )
    logged_in.post("/api/auth/logout", headers=H)
    assert actions(app) == ["setup", "login.ok", "password.change", "logout"]
