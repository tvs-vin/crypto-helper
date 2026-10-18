from sqlalchemy import select

from app.models import AuditLog, User
from tests.conftest import PASSWORD, H


def test_status_requires_setup_then_not(client, app):
    assert client.get("/api/setup/status").json() == {"setup_required": True}
    client.post(
        "/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H
    )
    assert client.get("/api/setup/status").json() == {"setup_required": False}


def test_setup_needs_correct_token(client):
    r = client.post("/api/setup", json={"token": "nope", "password": PASSWORD}, headers=H)
    assert r.status_code == 403


def test_setup_rejects_short_password(client, app):
    r = client.post(
        "/api/setup", json={"token": app.state.setup_token, "password": "short"}, headers=H
    )
    assert r.status_code == 422


def test_setup_creates_super_with_argon2id_hash(client, app):
    r = client.post(
        "/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H
    )
    assert r.status_code == 201
    with app.state.session_factory() as db:
        user = db.scalar(select(User))
        assert user.username == "super" and user.is_super
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash


def test_setup_impossible_once_a_user_exists(ready, app):
    r = ready.post("/api/setup", json={"token": "anything", "password": PASSWORD}, headers=H)
    assert r.status_code == 409


def test_setup_token_is_single_use_and_cleared(ready, app):
    assert app.state.setup_token is None


def test_setup_is_audited_without_secrets(ready, app):
    with app.state.session_factory() as db:
        rows = db.scalars(select(AuditLog)).all()
    assert [r.action for r in rows] == ["setup"]
    assert PASSWORD not in rows[0].detail
