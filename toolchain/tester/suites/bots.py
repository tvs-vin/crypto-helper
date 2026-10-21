"""Paper trading (12d): who may see, run and stop bots, and the kill switch. Creating bots and
tripping the kill switch only on the throwaway server: on a live one they'd stop the owner's
bots."""

from toolchain.tester.framework import check, expect, expect_status, skip_in_live

PLAN = {"strategy": "dca", "coins": {"BTC": "100"}, "currency": "usd", "initial": "100"}


@check("bots", "bots: 401 anonymous, 403 without bots.view, 200 with it")
def access(ctx):
    expect_status(ctx.client().get("/api/bots"), 401, "anonymous")
    other, _ = ctx.make_user(["prices.view"])
    expect_status(ctx.as_user(other).get("/api/bots"), 403, "without bots.view")
    viewer, _ = ctx.make_user(["bots.view"])
    c = ctx.as_user(viewer)
    r = c.get("/api/bots")
    expect_status(r, 200, "with bots.view")
    expect({"kill", "bots", "max"} <= set(r.json()), f"shape: {sorted(r.json())}")
    expect_status(c.get("/api/bots/meta"), 200, "the plan form's choices")
    expect_status(c.post("/api/bots", {"name": "t_x", "params": PLAN}), 403, "create, view only")
    expect_status(c.post("/api/bots/kill", {}), 403, "kill switch without bots.stop")
    expect_status(c.post("/api/bots/rearm", {"confirm": "REARM"}), 403, "re-arm, view only")


@check("bots", "a bot is checked, made, and deleted (spawn only)")
def lifecycle(ctx):
    skip_in_live(ctx, "would add a bot to the live server")
    bad = ctx.admin.post("/api/bots", {"name": "t_bad", "params": {**PLAN, "fee_pct": "50"}})
    expect_status(bad, 422, "a 50 % fee")
    r = ctx.admin.post("/api/bots", {"name": "t_bot", "params": PLAN, "limits": {}})
    expect_status(r, 201, "create")
    b = r.json()
    expect(b["status"] == "running" and b["limits"]["daily_loss_pct"] == "15", str(b)[:200])
    expect_status(ctx.admin.get(f"/api/bots/{b['id']}/orders.csv"), 200, "orders CSV")
    expect_status(ctx.admin.delete(f"/api/bots/{b['id']}"), 204, "delete")
    expect_status(ctx.admin.get(f"/api/bots/{b['id']}"), 404, "gone")


@check("bots", "kill switch: easy to stop, deliberate to re-arm, audited (spawn only)")
def kill_switch(ctx):
    skip_in_live(ctx, "would stop the live server's bots")
    stopper, _ = ctx.make_user(["bots.view", "bots.stop"])
    s = ctx.as_user(stopper)
    r = s.post("/api/bots/kill", {"reason": "tester drill"})
    expect_status(r, 200, "trip")
    expect(r.json()["kill"]["tripped"] is True, "not tripped")
    expect_status(s.post("/api/bots/rearm", {"confirm": "REARM"}), 403, "re-arm needs bots.run")
    expect_status(ctx.admin.post("/api/bots/rearm", {"confirm": "yes"}), 422, "without REARM")
    expect_status(ctx.admin.post("/api/bots/rearm", {"confirm": "REARM"}), 200, "re-arm")
    expect_status(ctx.admin.post("/api/bots/rearm", {"confirm": "REARM"}), 409, "twice")
    actions = [e["action"] for e in ctx.admin.get("/api/audit?q=bots.&limit=20").json()]
    expect("bots.kill" in actions and "bots.rearm" in actions, f"audit: {actions}")
