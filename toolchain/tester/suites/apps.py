"""Apps on top of permissions and the App manager, on throwaway t_* users. The
"off for everyone" check runs only on the throwaway server (it would affect real users)."""

from toolchain.tester.framework import check, expect, expect_status, skip_in_live


@check("apps", "401 anonymous, 403 without apps.manage")
def access(ctx):
    expect_status(ctx.client().get("/api/apps"), 401, "anonymous")
    name, _ = ctx.make_user(["wallets.view"])
    c = ctx.as_user(name)
    expect_status(c.get("/api/apps"), 403, "without apps.manage")
    expect_status(c.put("/api/apps/wallets/enabled", {"enabled": False}), 403, "switch")


@check("apps", "/me lists the apps an account can open")
def me(ctx):
    name, _ = ctx.make_user(["wallets.view"])
    apps = ctx.as_user(name).get("/api/auth/me").json()["apps"]
    expect(apps == ["settings", "notifications", "wallets", "transfers"], f"apps {apps}")


@check("apps", "an app switched off for an account blocks its endpoints, not others")
def per_account(ctx):
    name, uid = ctx.make_user(["wallets.view", "wallets.edit", "prices.view"])
    c = ctx.as_user(name)
    r = ctx.admin.put(f"/api/apps/accounts/{uid}", {"apps": ["transfers", "overview"]})
    expect_status(r, 200, "set apps")
    expect_status(c.get("/api/meta/networks"), 403, "Wallets-only endpoint")
    expect_status(c.get("/api/wallets"), 200, "wallet list (Transfers uses it)")
    expect_status(c.get("/api/me/preferences"), 200, "core endpoint")
    expect_status(ctx.admin.put(f"/api/apps/accounts/{uid}", {"apps": "all"}), 200, "all")
    expect_status(c.get("/api/meta/networks"), 200, "after allowing all")


@check("apps", "managers can't touch super, themselves, or apps they can't use")
def rules(ctx):
    mgr, mgr_id = ctx.make_user(["apps.manage", "wallets.view"])
    _, plain_id = ctx.make_user(["wallets.view"])
    m = ctx.as_user(mgr)
    accounts = m.get("/api/apps").json()["accounts"]
    super_id = next(a["id"] for a in accounts if a["is_super"])
    expect_status(m.put(f"/api/apps/accounts/{super_id}", {"apps": []}), 403, "super")
    expect_status(m.put(f"/api/apps/accounts/{mgr_id}", {"apps": []}), 403, "yourself")
    r = m.put(f"/api/apps/accounts/{plain_id}", {"apps": ["wallets"]})
    expect_status(r, 403, "switching off apps the manager can't use")
    expect_status(m.put("/api/apps/audit/enabled", {"enabled": False}), 403, "global audit")


@check("apps", "off for everyone spares super (throwaway server only)")
def global_switch(ctx):
    skip_in_live(ctx, "would turn an app off for real accounts")
    name, _ = ctx.make_user(["prices.view"])
    c = ctx.as_user(name)
    expect_status(ctx.admin.put("/api/apps/overview/enabled", {"enabled": False}), 200, "off")
    try:
        expect_status(c.get("/api/prices"), 403, "account while off")
        expect_status(ctx.admin.get("/api/prices"), 200, "super while off")
    finally:
        ctx.admin.put("/api/apps/overview/enabled", {"enabled": True})
    expect_status(c.get("/api/prices"), 200, "back on")
