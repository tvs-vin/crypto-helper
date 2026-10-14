from fastapi import Depends
from fastapi.testclient import TestClient

from app.deps import effective_permissions, require_permission
from app.models import User
from app.permissions import ALL_PERMISSIONS, PRESETS
from app.security import hash_password
from tests.conftest import PASSWORD, H


def test_presets_only_use_catalog_permissions():
    for perms in PRESETS.values():
        assert set(perms) <= ALL_PERMISSIONS


def test_super_has_every_permission_even_if_list_is_empty():
    u = User(username="super", password_hash="x", permissions=[], is_super=True)
    assert effective_permissions(u) == set(ALL_PERMISSIONS)


def test_require_permission_denies_and_allows(app):
    """The dependency every future endpoint uses: 401 w/o session, 403 w/o permission."""

    @app.get("/api/_probe")
    def probe(_=Depends(require_permission("audit.view"))):
        return {"ok": True}

    with TestClient(app) as c:
        c.post("/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H)
        assert c.get("/api/_probe").status_code == 401  # no session
        with app.state.session_factory() as db:
            db.add(
                User(
                    username="bob",
                    password_hash=hash_password(PASSWORD),
                    permissions=["wallets.view"],
                )
            )
            db.commit()
        c.post("/api/auth/login", json={"username": "bob", "password": PASSWORD}, headers=H)
        assert c.get("/api/_probe").status_code == 403  # logged in, lacks audit.view
        c.post("/api/auth/logout", headers=H)
        c.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
        assert c.get("/api/_probe").status_code == 200  # super passes
