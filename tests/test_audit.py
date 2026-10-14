from fastapi.testclient import TestClient

from tests.conftest import PASSWORD, H
from tests.test_users import PW2, as_user, create


def test_audit_requires_session_and_permission(logged_in, app):
    create(logged_in, "bob", ["wallets.view", "users.manage"])
    assert TestClient(app).get("/api/audit").status_code == 401
    assert as_user(app, "bob").get("/api/audit").status_code == 403


def test_audit_view_permission_is_enough(logged_in, app):
    create(logged_in, "aud", ["audit.view"])
    assert as_user(app, "aud").get("/api/audit").status_code == 200


def test_audit_newest_first_with_limit(logged_in):
    create(logged_in, "alice")
    create(logged_in, "bob2")
    rows = logged_in.get("/api/audit?limit=2").json()
    assert len(rows) == 2
    assert rows[0]["action"] == "user.create" and "bob2" in rows[0]["detail"]
    assert rows[0]["id"] > rows[1]["id"]
    assert {"time", "user_id", "username", "action", "detail", "source_ip"} <= set(rows[0])


def test_audit_limit_bounds(logged_in):
    assert logged_in.get("/api/audit?limit=0").status_code == 422
    assert logged_in.get("/api/audit?limit=1001").status_code == 422


def test_audit_has_no_write_or_delete_endpoints(logged_in):
    assert logged_in.post("/api/audit", json={}, headers=H).status_code == 405
    assert logged_in.delete("/api/audit", headers=H).status_code == 405


def test_full_audit_trail_never_contains_secrets(logged_in, app):
    create(logged_in, "bob", ["wallets.view"])
    bob = as_user(app, "bob")
    bob.post(
        "/api/auth/password",
        json={"current_password": PW2, "new_password": "bobs-new-passphrase"},
        headers=H,
    )
    TestClient(app).post(
        "/api/auth/login", json={"username": "bob", "password": "typo-in-password"}, headers=H
    )
    rows = logged_in.get("/api/audit?limit=1000").json()
    blob = str(rows)
    for secret in (PASSWORD, PW2, "bobs-new-passphrase", "typo-in-password", "$argon2"):
        assert secret not in blob
    actions = [r["action"] for r in reversed(rows)]
    assert actions == [
        "setup",
        "login.ok",
        "user.create",
        "login.ok",
        "password.change",
        "login.fail",
    ]
