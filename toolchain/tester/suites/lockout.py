from toolchain.tester.framework import PW, check, expect, expect_status


@check("lockout", "5 bad passwords lock the account; correct password is then refused")
def lockout(ctx):
    name, uid = ctx.make_user()
    c = ctx.client()
    for i in range(5):
        expect_status(c.login(name, f"wrong-password-{i}"), 401, f"bad attempt {i + 1}")
    expect_status(c.login(name, PW), 401, "correct password while locked")
    users = {u["id"]: u for u in ctx.admin.get("/api/users").json()}
    expect(users[uid]["locked"] is True, "user list does not show the lockout")


@check("lockout", "an admin password reset unlocks the account")
def reset_unlocks(ctx):
    name, uid = ctx.make_user()
    c = ctx.client()
    for i in range(5):
        c.login(name, f"wrong-password-{i}")
    new = "unlocked-by-admin-1"
    r = ctx.admin.patch(f"/api/users/{uid}", {"password": new})
    expect_status(r, 200, "admin password reset")
    expect(r.json()["locked"] is False, "still locked after reset")
    expect_status(ctx.client().login(name, new), 200, "login after reset")


@check("lockout", "failures that aren't consecutive do not lock")
def non_consecutive(ctx):
    name, _ = ctx.make_user()
    c = ctx.client()
    for _ in range(2):
        for i in range(4):
            c.login(name, f"wrong-password-{i}")
        expect_status(c.login(name, PW), 200, "login after 4 failures")
