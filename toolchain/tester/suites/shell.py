"""Console and Terminal: who may use them. Never runs a command or opens a session (that
needs 2FA and, for a terminal, a Linux password); only checks the doors are shut."""

from toolchain.tester.framework import check, expect, expect_status


@check("shell", "401 anonymous, 403 without the permissions")
def access(ctx):
    expect_status(ctx.client().get("/api/console/commands"), 401, "anonymous")
    name, _ = ctx.make_user(["wallets.view"])
    c = ctx.as_user(name)
    expect_status(c.get("/api/console/commands"), 403, "console list")
    expect_status(c.post("/api/console/run", {"command": "status"}), 403, "console run")
    body = {"password": "x", "code": "123456"}
    expect_status(c.post("/api/terminal/open", body), 403, "terminal open")


@check("shell", "both need 2FA on the account")
def needs_2fa(ctx):
    name, _ = ctx.make_user(["console.use"])
    c = ctx.as_user(name)
    expect_status(c.get("/api/console/commands"), 200, "list is fine")
    r = c.post("/api/console/run", {"command": "status"})
    expect_status(r, 403, "run without 2FA")
    expect("two-factor" in r.json()["detail"], f"reason: {r.json()['detail']}")


@check("shell", "only super can grant terminal access")
def super_grants_only(ctx):
    name, _ = ctx.make_user(["users.manage", "wallets.view"])
    r = ctx.as_user(name).post(
        "/api/users",
        {"username": "t_term", "password": "t-term-password-1", "permissions": ["terminal.use"]},
    )
    expect_status(r, 403, "admin granting terminal.use")


@check("shell", "commands outside the list are refused")
def only_the_list(ctx):
    r = ctx.admin.post("/api/console/run", {"command": "service uninstall --purge"})
    expect_status(r, 422, "a command line")
