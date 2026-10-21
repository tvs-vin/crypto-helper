from toolchain.tester.framework import PW, check, expect, expect_status

VIEWER = ["wallets.view", "prices.view"]


def _super_id(ctx) -> int:
    return next(u["id"] for u in ctx.admin.get("/api/users").json() if u["is_super"])


@check("users", "user endpoints: 401 anonymous, 403 without users.manage")
def access(ctx):
    name, _ = ctx.make_user(VIEWER)
    anon, viewer = ctx.client(), ctx.as_user(name)
    for path in ("/api/users", "/api/meta/permissions"):
        expect_status(anon.get(path), 401, f"anonymous GET {path}")
        expect_status(viewer.get(path), 403, f"viewer GET {path}")
    expect_status(
        viewer.post("/api/users", {"username": "t_nope", "password": PW}),
        403,
        "viewer creates user",
    )


@check("users", "user list never contains password hashes or secrets")
def no_secrets(ctx):
    ctx.make_user()
    # must_change_password is a yes/no rule, not a secret.
    text = ctx.admin.get("/api/users").text.replace("must_change_password", "")
    for bad in ("password", "$argon2", "totp_secret"):
        expect(bad not in text, f"user list contains {bad!r}")


@check("users", "username rules and the reserved names 'super' and 'list'")
def username_rules(ctx):
    for bad in ("ab", "x" * 33, "Alice", "bad name", "a/b"):
        r = ctx.admin.post("/api/users", {"username": bad, "password": PW})
        expect_status(r, 422, f"username {bad!r}")
    for reserved in ("super", "list"):
        r = ctx.admin.post("/api/users", {"username": reserved, "password": PW})
        expect_status(r, 400, f"reserved name {reserved!r}")


@check("users", "no second root: is_super can't be set on create or edit")
def no_second_root(ctx):
    r = ctx.admin.post("/api/users", {"username": "t_root", "password": PW, "is_super": True})
    expect_status(r, 422, "create with is_super")
    _, uid = ctx.make_user()
    expect_status(ctx.admin.patch(f"/api/users/{uid}", {"is_super": True}), 422, "patch is_super")


@check("users", "you can only grant permissions you hold")
def grant_only_held(ctx):
    mgr, _ = ctx.make_user(["users.manage", "wallets.view"])
    m = ctx.as_user(mgr)
    r = m.post(
        "/api/users",
        {"username": "t_esc1", "password": PW, "permissions": ["wallets.view", "audit.view"]},
    )
    expect_status(r, 403, "grant audit.view without holding it")
    _, bob = ctx.make_user(["wallets.view"])
    r = m.patch(f"/api/users/{bob}", {"permissions": ["wallets.view", "audit.view"]})
    expect_status(r, 403, "add audit.view on edit")


@check("users", "you can't manage a user who has permissions you lack")
def subset_rule(ctx):
    mgr, _ = ctx.make_user(["users.manage", "wallets.view"])
    _, aud = ctx.make_user(["audit.view"])
    m = ctx.as_user(mgr)
    for body in ({"permissions": []}, {"is_active": False}, {"password": "x" * 16}):
        expect_status(m.patch(f"/api/users/{aud}", body), 403, f"edit outranking user {body}")
    expect_status(m.delete(f"/api/users/{aud}"), 403, "delete outranking user")


@check("users", "nobody edits or deletes their own account")
def no_self_edit(ctx):
    mgr, mid = ctx.make_user(["users.manage", "wallets.view"])
    m = ctx.as_user(mgr)
    for body in ({"permissions": ["users.manage"]}, {"is_active": False}, {"password": "x" * 16}):
        expect_status(m.patch(f"/api/users/{mid}", body), 403, f"self edit {body}")
    expect_status(m.delete(f"/api/users/{mid}"), 403, "self delete")


@check("users", "super can't be edited or deleted, even by an admin")
def super_protected(ctx):
    adm, _ = ctx.make_user(
        [
            "wallets.view",
            "prices.view",
            "wallets.edit",
            "transfers.create",
            "audit.view",
            "users.manage",
        ]
    )
    a = ctx.as_user(adm)
    sid = _super_id(ctx)
    expect_status(a.patch(f"/api/users/{sid}", {"is_active": False}), 403, "admin disables super")
    expect_status(a.delete(f"/api/users/{sid}"), 403, "admin deletes super")


@check("users", "deactivating a user signs them out and blocks login")
def deactivate(ctx):
    name, uid = ctx.make_user()
    c = ctx.as_user(name)
    expect_status(ctx.admin.patch(f"/api/users/{uid}", {"is_active": False}), 200, "deactivate")
    expect_status(c.get("/api/auth/me"), 401, "existing session after deactivate")
    expect_status(ctx.client().login(name, PW), 401, "login while inactive")
    ctx.admin.patch(f"/api/users/{uid}", {"is_active": True})
    expect_status(ctx.client().login(name, PW), 200, "login after re-activate")


@check("users", "removing a permission takes effect on the next request")
def immediate_revoke(ctx):
    name, uid = ctx.make_user(["users.manage"])
    c = ctx.as_user(name)
    expect_status(c.get("/api/users"), 200, "before removal")
    ctx.admin.patch(f"/api/users/{uid}", {"permissions": []})
    expect_status(c.get("/api/users"), 403, "after removal")


@check("users", "deleting a user ends their session")
def delete_user(ctx):
    name, uid = ctx.make_user()
    c = ctx.as_user(name)
    expect_status(ctx.admin.delete(f"/api/users/{uid}"), 204, "delete")
    expect_status(c.get("/api/auth/me"), 401, "session after delete")


@check("users", "account rules: a new password or 2FA first; nothing else until then")
def account_rules(ctx):
    _, uid = ctx.make_user(["wallets.view"])
    name = next(u["username"] for u in ctx.admin.get("/api/users").json() if u["id"] == uid)
    c = ctx.as_user(name)
    expect_status(c.get("/api/wallets"), 200, "before any rule")
    r = ctx.admin.request("PATCH", f"/api/users/{uid}", {"must_change_password": True})
    expect_status(r, 200, "require a new password")
    r = c.get("/api/wallets")
    expect_status(r, 403, "anything else while a new password is due")
    expect(r.json().get("restricted") == "password", "the answer says what to do")
    expect(c.get("/api/auth/me").json()["restricted"] == "password", "/me says it too")
    expect_status(c.get("/api/onboarding"), 200, "the walkthrough still reads")
    same = {"current_password": PW, "new_password": PW}
    expect_status(c.post("/api/auth/password", same), 422, "the same password again")
    new = {"current_password": PW, "new_password": PW + "-new"}
    expect_status(c.post("/api/auth/password", new), 200, "a new password")
    expect_status(c.get("/api/wallets"), 200, "usable again")
    ctx.admin.request("PATCH", f"/api/users/{uid}", {"require_2fa": True})
    r = c.get("/api/wallets")
    expect(r.status == 403 and r.json().get("restricted") == "2fa", "2FA required")


@check("users", "onboarding steps for everyone; server setup for super only")
def onboarding(ctx):
    name, _ = ctx.make_user(["prices.view"])
    c = ctx.as_user(name)
    s = c.get("/api/onboarding").json()
    expect(s["server"] is None, "no server steps for a viewer")
    ids = [st["id"] for st in s["account"]]
    expect("wallets" not in ids, "no wallet step without wallets.edit")
    expect_status(c.post("/api/onboarding/steps/tour"), 200, "tick your own step")
    expect_status(c.post("/api/onboarding/steps/network"), 403, "a server step")
    expect_status(c.get("/api/server/network"), 403, "network settings without super")
    r = c.request(
        "PUT", "/api/server/network", {"hosts": ["127.0.0.1"], "allowed_networks": ["127.0.0.0/8"]}
    )
    expect_status(r, 403, "changing them without super")
    expect_status(ctx.admin.get("/api/server/network"), 200, "super reads them")


@check("users", "open a window remotely: users.manage; only signed-in accounts")
def open_window_remotely(ctx):
    _, uid = ctx.make_user(["wallets.view"])
    r = ctx.admin.post(f"/api/users/{uid}/open-window", {"panel": "wallets"})
    expect_status(r, 409, "someone who isn't signed in")
    name, _ = ctx.make_user(["wallets.view"])
    c = ctx.as_user(name)
    expect_status(c.post(f"/api/users/{uid}/open-window", {"panel": "wallets"}), 403,
                  "without users.manage")  # fmt: skip
    listed = ctx.admin.get("/api/users").json()
    expect(all("online" in u for u in listed), "users carry 'online'")
