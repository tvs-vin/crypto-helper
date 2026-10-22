"""12a: account rules, enforced by the server. An account that must pick a new password or turn
on two-factor login can do that and nothing else (checked against every route), and super
needs 2FA on a real install."""

import re

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import PASSWORD, H
from tests.test_route_audit import PUBLIC, routes
from tests.test_users import PW2, as_user, create

# What an account under a rule may still do, and why.
ALLOWED = {
    ("GET", "/api/auth/me"): "the app asks what the account must do",
    ("POST", "/api/auth/password"): "choosing the new password",
    ("POST", "/api/auth/totp/setup"): "turning on 2FA",
    ("POST", "/api/auth/totp/enable"): "turning on 2FA",
    ("POST", "/api/auth/totp/disable"): "refused anyway when 2FA is required",
    ("POST", "/api/auth/totp/recovery-codes"): "needs 2FA on, so not reachable before",
    ("GET", "/api/auth/sessions"): "seeing where you're signed in",
    ("DELETE", "/api/auth/sessions/{session_id}"): "signing a stolen session out",
    ("POST", "/api/auth/sessions/revoke-others"): "signing everything else out",
    ("GET", "/api/notifications/stream"): "security notifications keep arriving",
    ("GET", "/api/onboarding"): "the walkthrough shows what's left to do",
}


def enable_2fa(client, password=PW2) -> str:
    secret = client.post("/api/auth/totp/setup", headers=H).json()["secret"]
    r = client.post(
        "/api/auth/totp/enable",
        json={"password": password, "code": pyotp.TOTP(secret).now()},
        headers=H,
    )
    assert r.status_code == 200, r.text
    return secret


@pytest.fixture
def strict(monkeypatch):
    """An app as installed: super must turn on 2FA."""
    monkeypatch.setenv("BOT_SUPER_REQUIRES_TWO_FACTOR", "true")
    app = create_app(Settings(database_url="sqlite://", price_provider="mock", _env_file=None))
    with TestClient(app) as c:
        r = c.post(
            "/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H
        )
        assert r.status_code == 201
        r = c.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
        assert r.status_code == 200
        yield app, c


def test_super_must_turn_on_2fa_first(strict):
    _, c = strict
    me = c.get("/api/auth/me").json()
    assert (me["restricted"], me["requires_2fa"]) == ("2fa", True)
    r = c.get("/api/wallets")
    assert r.status_code == 403 and r.json() == {
        "detail": "Turn on two-factor login first (your account requires it).",
        "restricted": "2fa",
    }
    enable_2fa(c, PASSWORD)
    assert c.get("/api/auth/me").json()["restricted"] is None
    assert c.get("/api/wallets").status_code == 200
    r = c.post("/api/auth/totp/disable", json={"password": PASSWORD}, headers=H)
    assert r.status_code == 409 and "requires two-factor" in r.json()["detail"]


def test_the_setting_is_on_unless_switched_off(monkeypatch):
    monkeypatch.delenv("BOT_SUPER_REQUIRES_TWO_FACTOR")
    assert Settings(_env_file=None).super_requires_two_factor is True


def test_must_change_password_at_first_sign_in(logged_in, app):
    r = logged_in.post(
        "/api/users",
        json={
            "username": "newbie",
            "password": PASSWORD,
            "permissions": ["wallets.view"],
            "must_change_password": True,
        },
        headers=H,
    )
    assert r.status_code == 201 and r.json()["must_change_password"] is True
    assert "must_change_password" in logged_in.get("/api/audit?q=user.create").json()[0]["detail"]
    u = as_user(app, "newbie", PASSWORD)
    assert u.get("/api/auth/me").json()["restricted"] == "password"
    assert u.get("/api/wallets").json()["restricted"] == "password"
    same = {"current_password": PASSWORD, "new_password": PASSWORD}
    assert u.post("/api/auth/password", json=same, headers=H).status_code == 422
    new = {"current_password": PASSWORD, "new_password": "a-brand-new-passphrase"}
    assert u.post("/api/auth/password", json=new, headers=H).status_code == 200
    assert u.get("/api/auth/me").json()["restricted"] is None
    assert u.get("/api/wallets").status_code == 200


def test_admin_requires_a_new_password_or_2fa_later(logged_in, app):
    uid = create(logged_in, "later", ["wallets.view"]).json()["id"]
    u = as_user(app, "later")
    assert u.get("/api/wallets").status_code == 200
    r = logged_in.patch(f"/api/users/{uid}", json={"must_change_password": True}, headers=H)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert u.get("/api/wallets").json()["restricted"] == "password"  # from the next request
    logged_in.patch(f"/api/users/{uid}", json={"must_change_password": False}, headers=H)
    r = logged_in.patch(f"/api/users/{uid}", json={"require_2fa": True}, headers=H)
    assert r.json()["require_2fa"] is True
    assert u.get("/api/wallets").json()["restricted"] == "2fa"
    enable_2fa(u)
    assert u.get("/api/wallets").status_code == 200
    details = [e["detail"] for e in logged_in.get("/api/audit?q=user.update").json()]
    assert any("require_2fa=True" in d for d in details)
    assert any("must_change_password=True" in d for d in details)
    # An admin can lift it again; the person may then turn 2FA off.
    logged_in.patch(f"/api/users/{uid}", json={"require_2fa": False}, headers=H)
    r = u.post("/api/auth/totp/disable", json={"password": PW2}, headers=H)
    assert r.status_code == 200


def test_rules_need_users_manage_and_the_usual_limits(logged_in, app):
    uid = create(logged_in, "target", ["wallets.view"]).json()["id"]
    create(logged_in, "helper", ["users.manage", "wallets.view"])
    helper = as_user(app, "helper")
    r = helper.patch(f"/api/users/{uid}", json={"require_2fa": True}, headers=H)
    assert r.status_code == 200  # a user manager may
    viewer = as_user(app, "target")
    me_id = viewer.get("/api/auth/me").json()["id"]
    assert viewer.patch(f"/api/users/{me_id}", json={"require_2fa": False}).status_code == 403
    super_id = logged_in.get("/api/auth/me").json()["id"]
    r = helper.patch(f"/api/users/{super_id}", json={"must_change_password": True}, headers=H)
    assert r.status_code == 403  # super can't be changed here


def test_a_restricted_session_can_do_nothing_else(logged_in, app):
    """Every route, asked for real: only ALLOWED (and the public list) get past the rule."""
    create(logged_in, "stuck", [])
    uid = next(u["id"] for u in logged_in.get("/api/users").json() if u["username"] == "stuck")
    stuck = as_user(app, "stuck")
    logged_in.patch(f"/api/users/{uid}", json={"must_change_password": True}, headers=H)
    passed = []
    for method, path, _ in routes(app):
        if (method, path) in PUBLIC or (method, path) in ALLOWED or method == "WS":
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = stuck.request(method, url, headers=H, json={})
        if not (r.status_code == 403 and r.json().get("restricted") == "password"):
            passed.append(f"{method} {path} -> {r.status_code}")
    assert passed == []
    for method, path in ALLOWED:  # and the list isn't stale
        assert any((m, p) == (method, path) for m, p, _ in routes(app)), (method, path)
