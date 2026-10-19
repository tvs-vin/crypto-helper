"""7a: apps on top of permissions, the per-app switches, and the App manager rules."""

import pytest
from fastapi.testclient import TestClient

from app.apps import APPS, CORE_APPS
from tests.conftest import H
from tests.wallet_helpers import user_with, wallet

VIEW = ["wallets.view", "prices.view"]
ALL_APPS = list(APPS)
TRADER = ["wallets.view", "prices.view", "wallets.edit", "transfers.create"]


def uid(admin, name):
    return next(u["id"] for u in admin.get("/api/users").json() if u["username"] == name)


def set_apps(client, user_id, apps):
    return client.put(f"/api/apps/accounts/{user_id}", json={"apps": apps}, headers=H)


def switch(client, app_id, enabled):
    return client.put(f"/api/apps/{app_id}/enabled", json={"enabled": enabled}, headers=H)


def me_apps(client):
    return client.get("/api/auth/me").json()["apps"]


# ---- what /me reports ---------------------------------------------------------------------


def test_new_accounts_get_every_app_their_permissions_allow(logged_in, app):
    assert set(me_apps(logged_in)) == {*CORE_APPS, *APPS}
    viewer = user_with(app, logged_in, "viewer", ["wallets.view"])
    # No prices.view: no Overview; settings is always there.
    assert me_apps(viewer) == [*CORE_APPS, "wallets", "transfers", "trades"]


# ---- the server enforces it ---------------------------------------------------------------


def test_app_off_for_an_account_blocks_its_endpoints(logged_in, app):
    w = wallet(logged_in, "Shared")
    trader = user_with(app, logged_in, "trader", TRADER)
    assert trader.get("/api/meta/networks").status_code == 200
    assert (
        set_apps(logged_in, uid(logged_in, "trader"), ["transfers", "overview"]).status_code == 200
    )
    assert "wallets" not in me_apps(trader)
    r = trader.patch(f"/api/wallets/{w['id']}", json={"nickname": "x"}, headers=H)
    assert r.status_code == 403 and "turned off for your account" in r.json()["detail"]
    assert (
        trader.post("/api/wallets", json={"name": "n", "kind": "paper"}, headers=H).status_code
        == 403
    )
    # Transfers still lists wallets: it's switched on and needs them.
    assert trader.get("/api/wallets").status_code == 200
    assert trader.get("/api/portfolio").status_code == 200  # Overview uses it too
    set_apps(logged_in, uid(logged_in, "trader"), ["overview"])
    assert trader.get("/api/wallets").status_code == 403
    assert trader.get("/api/transfers").status_code == 403
    # Core things are never switched off.
    assert trader.get("/api/me/preferences").status_code == 200
    assert trader.get("/api/auth/sessions").status_code == 200


def test_switching_an_app_off_for_everyone_spares_super(logged_in, app):
    viewer = user_with(app, logged_in, "viewer", VIEW)
    assert switch(logged_in, "overview", False).status_code == 200
    r = viewer.get("/api/prices")
    assert r.status_code == 403 and "turned off for everyone" in r.json()["detail"]
    assert "overview" not in me_apps(viewer)
    assert logged_in.get("/api/prices").status_code == 200
    assert "overview" in me_apps(logged_in)
    switch(logged_in, "overview", True)
    assert viewer.get("/api/prices").status_code == 200


def test_switches_never_bypass_permissions(logged_in, app):
    viewer = user_with(app, logged_in, "viewer", VIEW)
    assert viewer.get("/api/audit").status_code == 403  # app on, permission missing
    assert viewer.get("/api/users").status_code == 403


# ---- the App manager ----------------------------------------------------------------------


def test_app_manager_needs_its_permission(logged_in, app):
    assert TestClient(app).get("/api/apps").status_code == 401
    viewer = user_with(app, logged_in, "viewer", VIEW)
    assert viewer.get("/api/apps").status_code == 403
    assert switch(viewer, "wallets", False).status_code == 403
    data = logged_in.get("/api/apps").json()
    assert [a["id"] for a in data["apps"]][:2] == ["wallets", "overview"]
    sup = next(a for a in data["accounts"] if a["is_super"])
    assert sup["locked"] and sup["chosen"] == "all"


def test_manager_rules(logged_in, app):
    mgr = user_with(app, logged_in, "mgr", ["apps.manage", "wallets.view", "prices.view"])
    user_with(app, logged_in, "viewer", VIEW)
    user_with(app, logged_in, "boss", ["users.manage", "wallets.view"])
    super_id = next(a["id"] for a in logged_in.get("/api/apps").json()["accounts"] if a["is_super"])
    # Only Wallets changes (an app mgr can use), so each refusal is down to its own rule.
    no_wallets = [a for a in ALL_APPS if a != "wallets"]
    for target, message in (
        (super_id, "Super always has every app"),
        (uid(logged_in, "mgr"), "your own apps"),
        (uid(logged_in, "boss"), "permissions you do not hold"),
    ):
        r = set_apps(mgr, target, no_wallets)
        assert r.status_code == 403 and message in r.json()["detail"], r.text
    viewer_id = uid(logged_in, "viewer")
    # mgr can't use Audit/Users: can't switch them for others either...
    r = set_apps(mgr, viewer_id, ["wallets", "overview", "transfers", "apps"])
    assert r.status_code == 403 and "audit" in r.json()["detail"]
    # ...but may leave them as they are while changing the rest.
    keep = [a for a in ALL_APPS if a != "overview"]  # only Overview changes (mgr can use it)
    r = set_apps(mgr, viewer_id, keep)
    assert r.status_code == 200, r.text
    assert r.json()["chosen"] == sorted(keep)
    assert switch(mgr, "audit", False).status_code == 403  # not one of mgr's apps
    assert switch(mgr, "overview", False).status_code == 200
    assert set_apps(mgr, viewer_id, ["nope"]).status_code == 422
    assert set_apps(mgr, viewer_id, "some").status_code == 422
    assert set_apps(mgr, 9999, ["wallets"]).status_code == 404


def test_all_means_new_apps_too_and_is_audited(logged_in, app):
    user_with(app, logged_in, "viewer", VIEW)
    vid = uid(logged_in, "viewer")
    set_apps(logged_in, vid, [])
    r = set_apps(logged_in, vid, "all")
    assert r.status_code == 200 and r.json()["chosen"] == "all"
    switch(logged_in, "transfers", False)
    actions = [e["action"] for e in logged_in.get("/api/audit?limit=20").json()]
    assert actions.count("apps.account") == 2 and "apps.switch" in actions


def test_turning_off_the_app_manager_locks_out_managers_but_not_super(logged_in, app):
    mgr = user_with(app, logged_in, "mgr", ["apps.manage", "wallets.view"])
    assert mgr.get("/api/apps").status_code == 200
    switch(logged_in, "apps", False)
    assert mgr.get("/api/apps").status_code == 403
    assert logged_in.get("/api/apps").status_code == 200


def test_unknown_app_in_a_dependency_is_a_programming_error():
    from app.deps import require_app

    with pytest.raises(ValueError):
        require_app("walets")


def test_every_window_is_an_app_or_core():
    """The JS window list and the server's app catalog must agree."""
    import re
    from pathlib import Path

    from app.apps import APPS, CORE_APPS

    js = (Path(__file__).parents[1] / "app/web/js/panels.js").read_text()
    windows = set(re.findall(r"^  (\w+): \{", js, re.M))
    assert windows == set(APPS) | set(CORE_APPS)


def test_window_limits_match_the_server():
    """panels.js `max` must equal app/apps.py max_windows (the server refuses more)."""
    import re
    from pathlib import Path

    from app.apps import CORE_APPS, max_windows

    js = (Path(__file__).parents[1] / "app/web/js/panels.js").read_text()
    for line in re.findall(r"^  (\w+): \{([^\n]*)", js, re.M):
        panel, rest = line
        m = re.search(r"max: (\d+)", rest)
        assert (int(m.group(1)) if m else 1) == max_windows(panel), panel
    assert all(max_windows(c) == 1 for c in CORE_APPS)
