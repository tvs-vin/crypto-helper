"""6c server side: your sessions, the 2FA QR code, uploaded themes, system status."""

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AuditLog
from tests.conftest import PASSWORD, H
from tests.test_users import PW2, as_user, create

DARK = json.loads((Path(__file__).resolve().parents[1] / "app/web/themes/dark.ctheme").read_text())


def theme_text(name="Midnight", **colors):
    t = json.loads(json.dumps(DARK))
    t["name"] = name
    t["colors"].update(colors)
    return json.dumps(t)


def actions(app):
    with app.state.session_factory() as db:
        return [r.action for r in db.scalars(select(AuditLog))]


# ---- sessions ----------------------------------------------------------------------------


def test_sessions_list_marks_this_one(logged_in, app):
    other = TestClient(app, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0"})
    other.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
    rows = logged_in.get("/api/auth/sessions").json()
    assert len(rows) == 2 and sum(r["current"] for r in rows) == 1
    assert {r["device"] for r in rows} >= {"Firefox on Linux"}
    assert all("token" not in json.dumps(r) for r in rows)


def test_end_another_session_but_not_this_one(logged_in, app):
    other = TestClient(app)
    other.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
    rows = logged_in.get("/api/auth/sessions").json()
    mine = next(r for r in rows if r["current"])
    theirs = next(r for r in rows if not r["current"])
    assert logged_in.delete(f"/api/auth/sessions/{mine['id']}", headers=H).status_code == 400
    assert logged_in.delete(f"/api/auth/sessions/{theirs['id']}", headers=H).status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    assert "session.revoke" in actions(app)


def test_cannot_touch_someone_elses_session(logged_in, app):
    create(logged_in, "bob")
    bob = as_user(app, "bob")
    bob_session = bob.get("/api/auth/sessions").json()[0]["id"]
    assert logged_in.delete(f"/api/auth/sessions/{bob_session}", headers=H).status_code == 404
    assert bob.get("/api/auth/me").status_code == 200


def test_sign_out_everywhere_else(logged_in, app):
    for _ in range(3):
        TestClient(app).post(
            "/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H
        )
    assert logged_in.post("/api/auth/sessions/revoke-others", headers=H).json() == {"revoked": 3}
    assert len(logged_in.get("/api/auth/sessions").json()) == 1


def test_sessions_need_a_session(client):
    assert client.get("/api/auth/sessions").status_code == 401


# ---- 2FA QR code -------------------------------------------------------------------------


def test_setup_includes_a_qr_code_image(logged_in):
    data = logged_in.post("/api/auth/totp/setup", headers=H).json()
    assert data["qr"].startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(data["qr"].split(",", 1)[1]).decode()
    assert svg.startswith("<svg") and "<script" not in svg and "<path" in svg


# ---- themes ------------------------------------------------------------------------------


def test_upload_list_get_and_use_a_theme(logged_in, app):
    r = logged_in.post("/api/themes", json={"content": theme_text("Midnight")}, headers=H)
    assert r.status_code == 201
    t = r.json()
    assert t["key"] == f"custom:{t['id']}" and t["mine"] and not t["published"]
    listed = logged_in.get("/api/themes").json()
    assert listed["builtin"] == ["dark", "light", "terminal", "template"]
    assert [c["name"] for c in listed["custom"]] == ["Midnight"]
    assert logged_in.get(f"/api/themes/{t['id']}").json()["name"] == "Midnight"
    p = logged_in.patch("/api/me/preferences", json={"theme": t["key"]}, headers=H)
    assert p.status_code == 200 and p.json()["theme"] == t["key"]
    assert "theme.upload" in actions(app)


@pytest.mark.parametrize(
    "content",
    [
        theme_text(accent="url(https://evil.example/x)"),
        theme_text(accent="red; background: url(x)"),
        "not json",
        json.dumps({"format": "something-else"}),
        theme_text() + " " * 40000,
    ],
)
def test_bad_themes_are_refused_without_echo(logged_in, content):
    r = logged_in.post("/api/themes", json={"content": content}, headers=H)
    assert r.status_code == 422
    assert "evil.example" not in r.text and "can't be used" in r.text


def test_private_until_published(logged_in, app):
    create(logged_in, "bob")
    bob = as_user(app, "bob")
    t = bob.post("/api/themes", json={"content": theme_text("Bobs")}, headers=H).json()
    assert logged_in.get(f"/api/themes/{t['id']}").status_code == 404  # private: not even super
    assert [c["name"] for c in logged_in.get("/api/themes").json()["custom"]] == []
    # Bob can't publish (no themes.publish); an admin can't publish someone else's private one.
    assert (
        bob.post(f"/api/themes/{t['id']}/publish", json={"published": True}, headers=H).status_code
        == 403
    )
    assert (
        logged_in.post(
            f"/api/themes/{t['id']}/publish", json={"published": True}, headers=H
        ).status_code
        == 404
    )


def test_admin_publishes_for_everyone_and_can_unpublish(logged_in, app):
    t = logged_in.post("/api/themes", json={"content": theme_text("House")}, headers=H).json()
    assert (
        logged_in.post(
            f"/api/themes/{t['id']}/publish", json={"published": True}, headers=H
        ).json()["published"]
        is True
    )
    create(logged_in, "bob")
    bob = as_user(app, "bob")
    seen = bob.get("/api/themes").json()["custom"]
    assert [(c["name"], c["mine"], c["owner"]) for c in seen] == [("House", False, "super")]
    assert bob.get(f"/api/themes/{t['id']}").status_code == 200
    assert bob.delete(f"/api/themes/{t['id']}", headers=H).status_code == 404  # not his
    logged_in.post(f"/api/themes/{t['id']}/publish", json={"published": False}, headers=H)
    assert bob.get(f"/api/themes/{t['id']}").status_code == 404
    assert {"theme.publish", "theme.unpublish"} <= set(actions(app))


def test_delete_own_theme(logged_in):
    t = logged_in.post("/api/themes", json={"content": theme_text("Gone")}, headers=H).json()
    assert logged_in.delete(f"/api/themes/{t['id']}", headers=H).status_code == 204
    assert logged_in.get(f"/api/themes/{t['id']}").status_code == 404


def test_theme_limit(logged_in, monkeypatch):
    monkeypatch.setattr("app.routers.themes.MAX_PER_USER", 2)
    for i in range(2):
        assert (
            logged_in.post(
                "/api/themes", json={"content": theme_text(f"T{i}")}, headers=H
            ).status_code
            == 201
        )
    r = logged_in.post("/api/themes", json={"content": theme_text("T3")}, headers=H)
    assert r.status_code == 409 and "at most 2" in r.text


@pytest.mark.parametrize("value", ["custom:", "custom:abc", "neon", "custom:1; x", "../dark"])
def test_theme_preference_format(logged_in, value):
    assert (
        logged_in.patch("/api/me/preferences", json={"theme": value}, headers=H).status_code == 422
    )


def test_admin_preset_can_publish(logged_in):
    assert "themes.publish" in logged_in.get("/api/meta/permissions").json()["presets"]["admin"]


# ---- system status -----------------------------------------------------------------------


def test_system_status_is_super_only(logged_in, app):
    data = logged_in.get("/api/system/status").json()
    assert data["database"]["revision"] == data["database"]["expected"]
    assert data["commands"]["update"] == "crypto-helper update" and "python" in data
    create(logged_in, "adm", ["users.manage", "audit.view"])
    assert as_user(app, "adm").get("/api/system/status").status_code == 403
    assert TestClient(app).get("/api/system/status").status_code == 401
    assert PW2
