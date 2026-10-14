"""Per-user preferences, always on a throwaway user."""

from toolchain.tester.framework import check, expect, expect_status


@check("preferences", "defaults, and PATCH changes only what's sent")
def patch(ctx):
    name, _ = ctx.make_user([])
    c = ctx.as_user(name)
    p = c.get("/api/me/preferences").json()
    expect(p["theme"] == "dark" and p["fiat"] == "usd", f"defaults {p}")
    r = c.patch("/api/me/preferences", {"theme": "terminal", "watchlist": ["btc", "eth"]})
    expect_status(r, 200, "patch")
    r = c.patch("/api/me/preferences", {"fiat": "eur"})
    p = r.json()
    expect(
        p["theme"] == "terminal" and p["fiat"] == "eur" and p["watchlist"] == ["BTC", "ETH"],
        f"merge lost something: {p}",
    )


@check("preferences", "window layout is bounded and validated")
def layout(ctx):
    name, _ = ctx.make_user([])
    c = ctx.as_user(name)
    ok = {"windows": [{"panel": "wallets", "x": 10, "y": 10, "w": 600, "h": 400}]}
    expect_status(c.patch("/api/me/preferences", {"layout": ok}), 200, "valid layout")
    for bad in (
        {"windows": [{"panel": "wallets", "x": 0, "y": 0, "w": 10, "h": 400}]},
        {"windows": [{"panel": "nope", "x": 0, "y": 0, "w": 600, "h": 400}]},
        {"windows": ok["windows"] * 2},
    ):
        expect_status(c.patch("/api/me/preferences", {"layout": bad}), 422, f"layout {bad}")
    expect_status(c.patch("/api/me/preferences", {"theme": "neon"}), 422, "bad theme")
    expect_status(c.patch("/api/me/preferences", {"surprise": 1}), 422, "unknown key")


@check("preferences", "preferences are private to each user")
def private(ctx):
    a, _ = ctx.make_user([])
    b, _ = ctx.make_user([])
    ctx.as_user(a).patch("/api/me/preferences", {"theme": "light"})
    expect(
        ctx.as_user(b).get("/api/me/preferences").json()["theme"] == "dark",
        "one user's theme leaked to another",
    )
    expect_status(ctx.client().get("/api/me/preferences"), 401, "anonymous")
