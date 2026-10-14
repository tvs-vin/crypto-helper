from toolchain.tester.framework import PW, check, expect, expect_status


@check("audit", "audit log: 401 anonymous, 403 without audit.view, 200 with it")
def access(ctx):
    expect_status(ctx.client().get("/api/audit"), 401, "anonymous")
    other, _ = ctx.make_user(["users.manage", "wallets.view"])
    expect_status(ctx.as_user(other).get("/api/audit"), 403, "without audit.view")
    aud, _ = ctx.make_user(["audit.view"])
    expect_status(ctx.as_user(aud).get("/api/audit"), 200, "with audit.view")


@check("audit", "newest first, limit respected and bounded")
def ordering(ctx):
    rows = ctx.admin.get("/api/audit?limit=5").json()
    expect(0 < len(rows) <= 5, f"got {len(rows)} rows")
    ids = [r["id"] for r in rows]
    expect(ids == sorted(ids, reverse=True), "not newest first")
    expect_status(ctx.admin.get("/api/audit?limit=0"), 422, "limit=0")
    expect_status(ctx.admin.get("/api/audit?limit=1001"), 422, "limit=1001")


@check("audit", "audit log can't be written or deleted through the API")
def read_only(ctx):
    expect_status(ctx.admin.post("/api/audit", {}), 405, "POST /api/audit")
    expect_status(ctx.admin.delete("/api/audit"), 405, "DELETE /api/audit")


@check("audit", "user changes are recorded with who did it")
def records_actor(ctx):
    name, _ = ctx.make_user()
    rows = ctx.admin.get("/api/audit?limit=20").json()
    hit = next((r for r in rows if r["action"] == "user.create" and name in r["detail"]), None)
    expect(hit is not None, "user.create entry not found")
    expect(hit["username"] == ctx.admin_username, f"actor recorded as {hit['username']}")


@check("audit", "audit log never contains passwords or hashes")
def no_secrets(ctx):
    name, _ = ctx.make_user()
    ctx.client().login(name, "typo-in-the-password")
    blob = ctx.admin.get("/api/audit?limit=1000").text
    for secret in (PW, ctx.admin_password, "typo-in-the-password", "$argon2"):
        expect(secret not in blob, "audit log contains a secret")
