import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AuditLog, Session, User
from app.permissions import ALL_PERMISSIONS, PRESETS
from tests.conftest import H

PW2 = "another-good-passphrase"


def create(client, username, permissions=(), **extra):
    return client.post(
        "/api/users",
        json={"username": username, "password": PW2, "permissions": list(permissions), **extra},
        headers=H,
    )


def as_user(app, username, password=PW2):
    """A separate browser logged in as `username` (no lifespan, shares the test DB)."""
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password}, headers=H)
    assert r.status_code == 200, r.text
    return c


def uid(app, username):
    with app.state.session_factory() as db:
        return db.scalar(select(User.id).where(User.username == username))


def audit(app, action):
    with app.state.session_factory() as db:
        return db.scalars(select(AuditLog).where(AuditLog.action == action)).all()


# ---- access to the endpoints -------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/users"),
        ("post", "/api/users"),
        ("patch", "/api/users/1"),
        ("delete", "/api/users/1"),
        ("get", "/api/meta/permissions"),
    ],
)
def test_user_endpoints_need_session_and_users_manage(logged_in, app, method, path):
    create(logged_in, "viewer1", PRESETS["viewer"])
    anon = TestClient(app)
    viewer = as_user(app, "viewer1")
    kwargs = {"headers": H}
    if method in ("post", "patch"):
        kwargs["json"] = {}
    assert getattr(anon, method)(path, **kwargs).status_code == 401
    assert getattr(viewer, method)(path, **kwargs).status_code == 403


def test_meta_permissions_lists_catalog_and_presets(logged_in):
    data = logged_in.get("/api/meta/permissions").json()
    assert set(data["permissions"]) == set(ALL_PERMISSIONS)
    assert data["presets"] == PRESETS


# ---- create --------------------------------------------------------------------------------


def test_super_creates_user_and_list_hides_secrets(logged_in, app):
    r = create(logged_in, "alice", PRESETS["trader"])
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice" and body["permissions"] == sorted(PRESETS["trader"])
    listing = logged_in.get("/api/users").json()
    assert [u["username"] for u in listing] == ["super", "alice"]
    text = str(listing).replace("must_change_password", "")  # a yes/no rule, not a secret
    assert "password" not in text and "totp_secret" not in text and "$argon2" not in text
    assert as_user(app, "alice").get("/api/auth/me").json()["username"] == "alice"


@pytest.mark.parametrize("name", ["ab", "x" * 33, "Alice", "bad name", "émile", "a/b"])
def test_username_rules(logged_in, name):
    assert create(logged_in, name).status_code == 422


def test_allowed_username_characters(logged_in):
    assert create(logged_in, "a.b-c_9").status_code == 201


def test_super_name_is_reserved(logged_in):
    assert create(logged_in, "super").status_code == 400


def test_no_second_root_via_extra_fields(logged_in, app):
    r = create(logged_in, "evil", is_super=True)
    assert r.status_code == 422
    with app.state.session_factory() as db:
        assert db.scalar(select(User).where(User.username == "evil")) is None


def test_duplicate_username_conflicts(logged_in):
    assert create(logged_in, "alice").status_code == 201
    assert create(logged_in, "alice").status_code == 409


def test_unknown_permission_rejected(logged_in):
    assert create(logged_in, "alice", ["wallets.view", "nuke.everything"]).status_code == 422


def test_short_password_rejected(logged_in):
    r = logged_in.post("/api/users", json={"username": "alice", "password": "short"}, headers=H)
    assert r.status_code == 422


def test_create_is_audited_without_password(logged_in, app):
    create(logged_in, "alice", ["wallets.view"])
    rows = audit(app, "user.create")
    assert len(rows) == 1 and "alice" in rows[0].detail and rows[0].username == "super"
    assert PW2 not in rows[0].detail


def test_cannot_grant_permissions_you_do_not_hold(logged_in, app):
    create(logged_in, "mgr", ["users.manage", "wallets.view"])
    mgr = as_user(app, "mgr")
    assert create(mgr, "ok1", ["wallets.view"]).status_code == 201
    r = create(mgr, "bad1", ["wallets.view", "audit.view"])
    assert r.status_code == 403
    assert uid(app, "bad1") is None


def test_manager_can_create_peer_with_same_permissions(logged_in, app):
    create(logged_in, "mgr", ["users.manage", "wallets.view"])
    assert create(as_user(app, "mgr"), "peer", ["users.manage", "wallets.view"]).status_code == 201


# ---- update --------------------------------------------------------------------------------


def test_super_cannot_be_edited_or_deleted_even_by_super(logged_in, app):
    sid = uid(app, "super")
    for body in ({"permissions": []}, {"is_active": False}, {"password": PW2}):
        assert logged_in.patch(f"/api/users/{sid}", json=body, headers=H).status_code == 403
    assert logged_in.delete(f"/api/users/{sid}", headers=H).status_code == 403


def test_admin_cannot_touch_super(logged_in, app):
    create(logged_in, "adm", PRESETS["admin"])
    adm = as_user(app, "adm")
    sid = uid(app, "super")
    assert adm.patch(f"/api/users/{sid}", json={"is_active": False}, headers=H).status_code == 403
    assert adm.delete(f"/api/users/{sid}", headers=H).status_code == 403


def test_nobody_edits_their_own_account(logged_in, app):
    create(logged_in, "mgr", ["users.manage", "wallets.view"])
    mgr = as_user(app, "mgr")
    me = uid(app, "mgr")
    for body in ({"permissions": ["users.manage"]}, {"is_active": False}, {"password": PW2}):
        assert mgr.patch(f"/api/users/{me}", json=body, headers=H).status_code == 403
    assert mgr.delete(f"/api/users/{me}", headers=H).status_code == 403


def test_cannot_edit_user_with_permissions_you_lack(logged_in, app):
    create(logged_in, "mgr", ["users.manage", "wallets.view"])
    create(logged_in, "auditor", ["audit.view"])
    mgr = as_user(app, "mgr")
    aid = uid(app, "auditor")
    # Even removing their permissions or disabling them is refused: they outrank mgr.
    assert mgr.patch(f"/api/users/{aid}", json={"permissions": []}, headers=H).status_code == 403
    assert mgr.patch(f"/api/users/{aid}", json={"is_active": False}, headers=H).status_code == 403
    assert mgr.patch(f"/api/users/{aid}", json={"password": PW2}, headers=H).status_code == 403
    assert mgr.delete(f"/api/users/{aid}", headers=H).status_code == 403


def test_cannot_add_permission_you_lack_on_edit(logged_in, app):
    create(logged_in, "mgr", ["users.manage", "wallets.view"])
    create(logged_in, "bob", ["wallets.view"])
    mgr = as_user(app, "mgr")
    bid = uid(app, "bob")
    r = mgr.patch(
        f"/api/users/{bid}", json={"permissions": ["wallets.view", "audit.view"]}, headers=H
    )
    assert r.status_code == 403
    with app.state.session_factory() as db:
        assert db.get(User, bid).permissions == ["wallets.view"]


def test_manager_can_add_held_and_remove_permissions(logged_in, app):
    create(logged_in, "mgr", ["users.manage", "wallets.view", "prices.view"])
    create(logged_in, "bob", ["wallets.view"])
    mgr = as_user(app, "mgr")
    bid = uid(app, "bob")
    r = mgr.patch(f"/api/users/{bid}", json={"permissions": ["prices.view"]}, headers=H)
    assert r.status_code == 200 and r.json()["permissions"] == ["prices.view"]
    detail = audit(app, "user.update")[-1].detail
    assert "+prices.view" in detail and "-wallets.view" in detail


def test_unknown_permission_on_edit_rejected(logged_in, app):
    create(logged_in, "bob")
    r = logged_in.patch(f"/api/users/{uid(app, 'bob')}", json={"permissions": ["x.y"]}, headers=H)
    assert r.status_code == 422


def test_cannot_set_is_super_via_patch(logged_in, app):
    create(logged_in, "bob")
    r = logged_in.patch(f"/api/users/{uid(app, 'bob')}", json={"is_super": True}, headers=H)
    assert r.status_code == 422


def test_deactivate_revokes_sessions_and_blocks_login(logged_in, app):
    create(logged_in, "bob", ["wallets.view"])
    bob = as_user(app, "bob")
    bid = uid(app, "bob")
    r = logged_in.patch(f"/api/users/{bid}", json={"is_active": False}, headers=H)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert bob.get("/api/auth/me").status_code == 401
    with app.state.session_factory() as db:
        assert db.scalar(select(Session).where(Session.user_id == bid)) is None
    login = TestClient(app).post(
        "/api/auth/login", json={"username": "bob", "password": PW2}, headers=H
    )
    assert login.status_code == 401
    # Re-activate and they can log in again.
    logged_in.patch(f"/api/users/{bid}", json={"is_active": True}, headers=H)
    as_user(app, "bob")


def test_password_reset_revokes_sessions_unlocks_and_is_audited(logged_in, app):
    create(logged_in, "bob")
    bob = as_user(app, "bob")
    bid = uid(app, "bob")
    anon = TestClient(app)
    for _ in range(5):
        anon.post(
            "/api/auth/login", json={"username": "bob", "password": "wrong-wrong-wrong"}, headers=H
        )
    assert logged_in.get("/api/users").json()[1]["locked"] is True
    new_pw = "reset-by-the-admin-1"
    r = logged_in.patch(f"/api/users/{bid}", json={"password": new_pw}, headers=H)
    assert r.status_code == 200 and r.json()["locked"] is False
    assert bob.get("/api/auth/me").status_code == 401
    as_user(app, "bob", new_pw)
    row = audit(app, "user.update")[-1]
    assert "password reset" in row.detail and new_pw not in row.detail


def test_patch_missing_user_is_404(logged_in):
    assert logged_in.patch("/api/users/999", json={}, headers=H).status_code == 404
    assert logged_in.delete("/api/users/999", headers=H).status_code == 404


# ---- delete --------------------------------------------------------------------------------


def test_delete_user_removes_sessions_and_is_audited(logged_in, app):
    create(logged_in, "bob")
    bob = as_user(app, "bob")
    bid = uid(app, "bob")
    assert logged_in.delete(f"/api/users/{bid}", headers=H).status_code == 204
    assert bob.get("/api/auth/me").status_code == 401
    assert uid(app, "bob") is None
    with app.state.session_factory() as db:
        assert db.scalar(select(Session).where(Session.user_id == bid)) is None
    assert "bob" in audit(app, "user.delete")[0].detail


def test_manager_can_delete_lower_user(logged_in, app):
    create(logged_in, "mgr", ["users.manage", "wallets.view"])
    create(logged_in, "bob", ["wallets.view"])
    mgr = as_user(app, "mgr")
    assert mgr.delete(f"/api/users/{uid(app, 'bob')}", headers=H).status_code == 204


def test_deleted_username_can_be_reused(logged_in, app):
    create(logged_in, "bob")
    logged_in.delete(f"/api/users/{uid(app, 'bob')}", headers=H)
    assert create(logged_in, "bob").status_code == 201


# ---- permission changes take effect immediately ------------------------------------------


def test_removed_permission_takes_effect_on_existing_session(logged_in, app):
    create(logged_in, "bob", ["users.manage"])
    bob = as_user(app, "bob")
    assert bob.get("/api/users").status_code == 200
    logged_in.patch(f"/api/users/{uid(app, 'bob')}", json={"permissions": []}, headers=H)
    assert bob.get("/api/users").status_code == 403
