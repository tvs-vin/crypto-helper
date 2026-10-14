import secrets

from toolchain.tester.framework import PW, check, expect, expect_status


@check("auth", "login sets an HttpOnly, SameSite=Strict session cookie")
def login_cookie(ctx):
    name, _ = ctx.make_user()
    c = ctx.client()
    r = c.login(name, PW)
    expect_status(r, 200, "login")
    raw = ", ".join(r.raw_headers.get_all("set-cookie") or []).lower()
    expect("httponly" in raw, "cookie is not HttpOnly")
    expect("samesite=strict" in raw, "cookie is not SameSite=Strict")


@check("auth", "wrong password and unknown user give identical answers")
def no_user_enumeration(ctx):
    name, _ = ctx.make_user()
    c = ctx.client()
    a = c.login(name, "definitely-wrong-pw")
    b = c.login("ghost_" + secrets.token_hex(4), "definitely-wrong-pw")
    expect(a.status == b.status == 401, f"statuses {a.status}/{b.status}")
    expect(a.text == b.text, "error bodies differ, which leaks whether a user exists")


@check("auth", "/me needs a session and returns the right user")
def me(ctx):
    expect_status(ctx.client().get("/api/auth/me"), 401, "/me anonymous")
    name, _ = ctx.make_user(["wallets.view"])
    data = ctx.as_user(name).get("/api/auth/me").json()
    expect(data["username"] == name, f"/me returned {data}")
    expect(data["permissions"] == ["wallets.view"], f"permissions {data['permissions']}")
    expect("password_hash" not in data and "totp_secret" not in data, "/me leaks secrets")


@check("auth", "super's /me lists every permission")
def super_me(ctx):
    data = ctx.admin.get("/api/auth/me").json()
    expect(data["is_super"] is True, "admin is not super")
    perms = ctx.admin.get("/api/meta/permissions").json()["permissions"]
    expect(set(data["permissions"]) == set(perms), "super is missing permissions")


@check("auth", "a forged session cookie is rejected")
def forged_cookie(ctx):
    c = ctx.client()
    r = c.get("/api/auth/me", headers={"Cookie": "session=" + secrets.token_urlsafe(32)})
    expect_status(r, 401, "/me with forged cookie")


@check("auth", "logout ends the session")
def logout(ctx):
    name, _ = ctx.make_user()
    c = ctx.as_user(name)
    cookie = c.session_cookie().value
    expect_status(c.post("/api/auth/logout"), 200, "logout")
    # Replay the old token explicitly: it must be dead server-side, not just cleared locally.
    r = ctx.client().get("/api/auth/me", headers={"Cookie": f"session={cookie}"})
    expect_status(r, 401, "/me with logged-out token")


@check("auth", "change password: revokes other sessions, old password stops working")
def change_password(ctx):
    name, _ = ctx.make_user()
    a, b = ctx.as_user(name), ctx.as_user(name)
    new = "tester-new-passphrase"
    r = a.post("/api/auth/password", {"current_password": PW, "new_password": new})
    expect_status(r, 200, "change password")
    expect_status(a.get("/api/auth/me"), 200, "current session after change")
    expect_status(b.get("/api/auth/me"), 401, "other session after change")
    expect_status(ctx.client().login(name, PW), 401, "login with old password")
    expect_status(ctx.client().login(name, new), 200, "login with new password")


@check("auth", "change password rejects wrong current and too-short new")
def change_password_bad(ctx):
    name, _ = ctx.make_user()
    c = ctx.as_user(name)
    r = c.post(
        "/api/auth/password",
        {"current_password": "wrong-wrong-wrong", "new_password": "tester-new-passphrase"},
    )
    expect_status(r, 403, "wrong current password")
    r = c.post("/api/auth/password", {"current_password": PW, "new_password": "short"})
    expect_status(r, 422, "short new password")
