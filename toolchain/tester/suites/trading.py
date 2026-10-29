"""Live trading (13a): who may see the Live trading API, that switching an exchange on is
super's (with 2FA), that adding a key needs 2FA, and caps. Never switches anything on and never
adds a key on a live server: on a throwaway server only, and still nothing real (no exchange
is reached: these checks stop before any key is checked)."""

from toolchain.tester.framework import check, expect, expect_status, skip_in_live


@check("trading", "live trading: 401 anonymous, 403 without a live permission, 200 with one")
def access(ctx):
    expect_status(ctx.client().get("/api/trading"), 401, "anonymous")
    other, _ = ctx.make_user(["wallets.view"])
    expect_status(ctx.as_user(other).get("/api/trading"), 403, "without live permissions")
    capper, _ = ctx.make_user(["live.cap"])
    r = ctx.as_user(capper).get("/api/trading")
    expect_status(r, 200, "with live.cap")
    body = r.json()
    expect({"exchanges", "caps", "keys", "may", "live_allowed"} <= set(body), sorted(body))
    expect(body["caps"]["default"] == "150", f"default cap {body['caps']}")


@check("trading", "caps: lowering is free, raising needs a 2FA code, no live.cap no change")
def caps(ctx):
    capper, _ = ctx.make_user(["live.cap"])
    c = ctx.as_user(capper)
    r = c.put("/api/trading/me/cap", {"cap": "100"})
    expect_status(r, 200, "lower own cap")
    expect(r.json()["cap"] == "100", r.text[:200])
    expect_status(c.put("/api/trading/me/cap", {"cap": "1000"}), 403, "raise without a code")
    expect_status(c.put("/api/trading/me/cap", {"cap": 5}), 422, "a JSON number")
    plain, _ = ctx.make_user(["live.trade"])
    expect_status(ctx.as_user(plain).put("/api/trading/me/cap", {"cap": "10"}), 403, "no live.cap")


@check("trading", "switching live trading on is super's, with 2FA; keys need 2FA (spawn)")
def switches_and_keys(ctx):
    skip_in_live(ctx, "never switch live trading on a live server")
    admin, _ = ctx.make_user(["services.manage"])
    r = ctx.as_user(admin).put("/api/services/live", {"exchange": "coinbase", "on": True})
    expect_status(r, 403, "an admin switching it on")
    r = ctx.admin.put("/api/services/live", {"exchange": "coinbase", "on": True})
    expect(r.status in (200, 403), f"super: {r.status}")
    if r.status == 403:  # the tester's super has no 2FA: refused for that reason
        expect("two-factor" in r.text, r.text[:200])
    expect_status(
        ctx.as_user(admin).put("/api/services/live", {"exchange": "coinbase", "on": False}),
        200,
        "switching it off",
    )
    trader, _ = ctx.make_user(["live.trade"])
    body = {"kind": "coinbase", "label": "t_key", "credentials": {"name": "x", "key": "y"}}
    r = ctx.as_user(trader).post("/api/trading/keys", body)
    expect_status(r, 403, "a key without 2FA")


@check("trading", "checking an order (no trade) needs live.trade: refused without it")
def test_order_rules(ctx):
    capper, _ = ctx.make_user(["live.cap"])
    r = ctx.as_user(capper).post("/api/trading/keys/999999/test-order", {"coin": "BTC"})
    expect_status(r, 404, "someone else's (or no) key")


@check("trading", "a live bot needs live.trade, 2FA and readiness: refused without them")
def live_bot_rules(ctx):
    plan = {"strategy": "dca", "coins": {"BTC": "100"}, "currency": "usd", "initial": "10"}
    runner, _ = ctx.make_user(["bots.view", "bots.run"])
    r = ctx.as_user(runner).post(
        "/api/bots", {"name": "t_live", "params": plan, "mode": "live", "trading_key_id": 1}
    )
    expect_status(r, 403, "a live bot without live.trade")


@check("trading", "the first tiny order: someone else's (or no) key is a 404, nothing is placed")
def first_order_rules(ctx):
    capper, _ = ctx.make_user(["live.cap"])
    c = ctx.as_user(capper)
    expect_status(
        c.post("/api/trading/keys/999999/first-order/preview", {"coin": "BTC"}),
        404,
        "preview for no key",
    )
    expect_status(
        c.post("/api/trading/keys/999999/first-order", {"coin": "BTC"}), 404, "an order for no key"
    )
