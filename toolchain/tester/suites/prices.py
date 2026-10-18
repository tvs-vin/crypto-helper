"""Prices, portfolio, history settings and extra coins.

Works against the mock (spawn) and real CoinGecko (live): it only checks the shape and
rules, never particular prices. In live mode it doesn't add coins to your catalog."""

from decimal import Decimal

from toolchain.tester.framework import Skip, check, expect, expect_status, skip_in_live


@check("prices", "prices: 401 anonymous, 403 without prices.view")
def access(ctx):
    expect_status(ctx.client().get("/api/prices"), 401, "anonymous")
    name, _ = ctx.make_user(["wallets.view"])
    expect_status(ctx.as_user(name).get("/api/prices"), 403, "without prices.view")


@check("prices", "every built-in coin is priced, with source and time")
def all_prices(ctx):
    r = ctx.admin.get("/api/prices?symbols=BTC,ETH,SOL,USDC,NOTACOIN")
    if r.status == 503:
        raise AssertionError(f"prices unavailable: {r.json()['detail']}")
    expect_status(r, 200, "prices")
    data = r.json()
    expect(
        [p["symbol"] for p in data["prices"]] == ["BTC", "ETH", "SOL", "USDC"],
        f"priced {[p['symbol'] for p in data['prices']]}",
    )
    expect(data["unpriced"] == ["NOTACOIN"], "unknown symbols should be listed, not an error")
    expect(data["source"] and data["as_of"] and "attribution" in data, "missing source/as_of")
    for p in data["prices"]:
        expect("e" not in p["price"].lower(), f"price {p['price']} uses an exponent")
        expect(Decimal(p["price"]) > 0, f"{p['symbol']} price isn't positive")


@check("prices", "fiat choice and validation")
def fiats(ctx):
    r = ctx.admin.get("/api/prices?symbols=BTC&fiat=jpy")
    expect_status(r, 200, "jpy")
    expect(r.json()["fiat"] == "jpy", "fiat not echoed")
    expect_status(ctx.admin.get("/api/prices?fiat=doge"), 422, "unknown fiat")
    sup = ctx.admin.get("/api/prices/supported").json()
    expect(sup["fiats"] == ["usd", "eur", "gbp", "jpy", "cad", "aud"], f"fiats {sup['fiats']}")


@check("prices", "portfolio values a throwaway wallet and needs both permissions")
def portfolio(ctx):
    w = ctx.make_wallet()
    r = ctx.admin.request("PUT", f"/api/wallets/{w['id']}/holdings/BTC", {"amount": "0.5"})
    expect_status(r, 200, "set BTC")
    data = ctx.admin.get("/api/portfolio?fiat=usd").json()
    mine = next(x for x in data["wallets"] if x["id"] == w["id"])
    price = Decimal(
        next(c for c in ctx.admin.get("/api/prices?symbols=BTC").json()["prices"])["price"]
    )
    expected = (Decimal("0.5") * price).quantize(Decimal("0.01"))
    expect(Decimal(mine["value"]) == expected, f"value {mine['value']} != {expected}")
    name, _ = ctx.make_user(["wallets.view"])
    expect_status(ctx.as_user(name).get("/api/portfolio"), 403, "portfolio without prices.view")


@check("prices", "history settings: validated, audited, restored afterwards")
def history_settings(ctx):
    original = ctx.admin.get("/api/prices/history/settings").json()["settings"]
    try:
        bad = {**original, "coarse_interval_minutes": 45}
        expect_status(
            ctx.admin.request("PUT", "/api/prices/history/settings", bad),
            422,
            "candle size that doesn't divide a day",
        )
        changed = {**original, "fine_keep_hours": original["fine_keep_hours"] + 1}
        r = ctx.admin.request("PUT", "/api/prices/history/settings", changed)
        expect_status(r, 200, "valid change")
        name, _ = ctx.make_user(["prices.view"])
        expect_status(
            ctx.as_user(name).request("PUT", "/api/prices/history/settings", original),
            403,
            "without prices.manage",
        )
    finally:
        ctx.admin.request("PUT", "/api/prices/history/settings", original)


@check("prices", "extra coins: verified, look-alikes need confirming, built-ins protected")
def extra_coins(ctx):
    skip_in_live(ctx, "would change your coin list")
    source = ctx.admin.get("/api/prices?symbols=BTC").json().get("source", "")
    if not source.startswith("Mock"):
        raise Skip("uses the mock's practice coins (mockcoin, fake-one)")
    expect_status(
        ctx.admin.post("/api/coins", {"coingecko_id": "mockcoin", "symbol": "BTC"}),
        409,
        "taking a built-in symbol",
    )
    r = ctx.admin.post("/api/coins", {"coingecko_id": "fake-one"})
    expect_status(r, 409, "look-alike without confirm")
    expect(r.json()["lookalike_count"] == 1, "look-alikes not reported")
    expect_status(
        ctx.admin.post("/api/coins", {"coingecko_id": "nope-not-real"}),
        404,
        "coin CoinGecko doesn't know",
    )
    expect_status(ctx.admin.post("/api/coins", {"coingecko_id": "mockcoin"}), 201, "add")
    expect(ctx.admin.get("/api/prices?symbols=MOCK").json()["prices"], "new coin not priced")
    expect_status(ctx.admin.delete("/api/coins/MOCK"), 204, "remove")
    expect_status(ctx.admin.delete("/api/coins/BTC"), 409, "remove a built-in")


@check("prices", "price alerts: 403 without prices.view; add, refused values, delete")
def alerts(ctx):
    name, _ = ctx.make_user(["wallets.view"])
    expect_status(ctx.as_user(name).get("/api/price-alerts"), 403, "without prices.view")
    name, _ = ctx.make_user(["prices.view"])
    c = ctx.as_user(name)
    body = {"symbol": "BTC", "kind": "above", "value": "999999999999", "fiat": "usd"}
    r = c.post("/api/price-alerts", body)
    expect_status(r, 201, "add")
    a = r.json()
    expect(a["state"] == "armed" and a["text"] == "BTC goes above 999,999,999,999 USD", f"{a}")
    for bad in (
        {"value": "-1"},
        {"value": 5},
        {"symbol": "NOTACOIN"},
        {"kind": "move", "value": "0"},
    ):
        expect_status(c.post("/api/price-alerts", {**body, **bad}), 422, f"{bad}")
    expect_status(c.delete(f"/api/price-alerts/{a['id']}"), 204, "delete")
    expect(c.get("/api/price-alerts").json()["alerts"] == [], "still listed")
