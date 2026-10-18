"""The Services window's API. Read-only against a live server; switching features (which
affects everyone) only on the throwaway server, and always switched back."""

from toolchain.tester.framework import check, expect, expect_status, skip_in_live


@check("services", "401 anonymous, 403 without services.manage")
def access(ctx):
    expect_status(ctx.client().get("/api/services"), 401, "anonymous")
    name, _ = ctx.make_user(["wallets.view"])
    c = ctx.as_user(name)
    expect_status(c.get("/api/services"), 403, "overview")
    expect_status(c.put("/api/services/features", {"paper_wallets": False}), 403, "features")
    expect_status(c.post("/api/services/embed/switch", {"on": True}), 403, "switch")
    expect_status(c.post("/api/services/selftest"), 403, "self-test")


@check("services", "overview: agent state, features, self-test")
def overview(ctx):
    r = ctx.admin.get("/api/services")
    expect_status(r, 200, "overview")
    d = r.json()
    expect(set(d["features"]) >= {"paper_wallets", "practice_transfers", "practice_prices",
                                  "price_history"}, f"features {d['features']}")  # fmt: skip
    expect("running" in d["selftest"], "no self-test state")
    if not d["agent"]["available"]:
        expect(d["agent"]["command"].endswith("agent enable"), "no command to turn it on")


@check("services", "unknown services and bad bodies are refused")
def refusals(ctx):
    expect_status(ctx.admin.post("/api/services/web/switch", {"on": False}), 404, "web off")
    expect_status(ctx.admin.post("/api/services/agent/restart"), 404, "agent restart")
    expect_status(ctx.admin.post("/api/services/embed/switch", {}), 422, "no on")
    expect_status(ctx.admin.put("/api/services/features", {"nope": True}), 422, "unknown feature")


@check("services", "feature switches take effect (throwaway server only)")
def switches(ctx):
    skip_in_live(ctx, "would switch features off for real users")
    a = ctx.make_wallet()
    b = ctx.make_wallet()
    ctx.admin.put(f"/api/wallets/{a['id']}/holdings/BTC", {"amount": "1"})
    body = {"from_wallet_id": a["id"], "to_wallet_id": b["id"], "symbol": "BTC", "amount": "0.1"}
    expect_status(ctx.admin.put("/api/services/features", {"paper_wallets": False,
                  "practice_transfers": False}), 200, "off")  # fmt: skip
    try:
        expect_status(
            ctx.admin.post("/api/wallets", {"name": "t_p", "kind": "paper"}), 403, "paper"
        )
        expect_status(ctx.admin.post("/api/transfers", body), 403, "transfer")
    finally:
        ctx.admin.put("/api/services/features", {"paper_wallets": True, "practice_transfers": True})
    expect_status(ctx.admin.post("/api/transfers", body), 201, "transfer after switching back")


@check("services", "system switches without an agent say how to turn it on")
def no_agent(ctx):
    if ctx.admin.get("/api/services").json()["agent"]["available"]:
        from toolchain.tester.framework import Skip

        raise Skip("an agent is running; not switching real services")
    r = ctx.admin.post("/api/services/embed/switch", {"on": True})
    expect_status(r, 503, "switch without agent")
    expect("agent enable" in r.json()["detail"], "no hint")
