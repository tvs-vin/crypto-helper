"""Wallets, holdings and simulated transfers. Uses throwaway t_* wallets only."""

from toolchain.tester.framework import check, expect, expect_status

SEED12 = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)
NOTE = "end-to-end tester"


def _hold(ctx, wid, symbol, amount):
    r = ctx.admin.request("PUT", f"/api/wallets/{wid}/holdings/{symbol}", {"amount": amount})
    expect_status(r, 200, f"set {symbol} on wallet {wid}")


def _send(client, src, dst, symbol, amount):
    return client.post(
        "/api/transfers",
        {
            "from_wallet_id": src,
            "to_wallet_id": dst,
            "symbol": symbol,
            "amount": amount,
            "note": NOTE,
        },
    )


def _amounts(ctx, wid) -> dict:
    return {
        h["symbol"]: h["amount"] for h in ctx.admin.get(f"/api/wallets/{wid}").json()["holdings"]
    }


@check("wallets", "wallet endpoints: 401 anonymous, viewer reads but can't write")
def access(ctx):
    w = ctx.make_wallet()
    expect_status(ctx.client().get("/api/wallets"), 401, "anonymous list")
    name, _ = ctx.make_user(["wallets.view"])
    viewer = ctx.as_user(name)
    expect_status(viewer.get("/api/wallets"), 200, "viewer list")
    expect_status(
        viewer.post("/api/wallets", {"name": "t_nope", "kind": "paper"}), 403, "viewer creates"
    )
    expect_status(_send(viewer, w["id"], w["id"], "BTC", "1"), 403, "viewer transfers")


@check("wallets", "nickname, two colors, user tags and built-in tags")
def presentation(ctx):
    w = ctx.make_wallet(
        "onchain",
        network="ethereum",
        nickname="Tester 🦊",
        address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        color_primary="#ff0000",
        color_scheme="complementary",
        tags=["long-term", "testing"],
    )
    expect(w["display_name"] == "Tester 🦊", f"display_name {w['display_name']!r}")
    expect(w["colors"]["secondary"] == "#00ffff", f"auto secondary {w['colors']}")
    expect(w["tags"] == ["long-term", "testing"], f"tags {w['tags']}")
    for t in ("kind:onchain", "network:ethereum", "address:yes"):
        expect(t in w["system_tags"], f"missing built-in tag {t}")
    r = ctx.admin.patch(f"/api/wallets/{w['id']}", {"tags": ["kind:fake"]})
    expect_status(r, 422, "user tag pretending to be built-in")


@check("wallets", "seed phrases and private keys are refused and never echoed")
def secret_guard(ctx):
    r = ctx.admin.post("/api/wallets", {"name": "t_seed", "kind": "paper", "notes": SEED12})
    expect_status(r, 422, "seed phrase in notes")
    expect("abandon" not in r.text, "the seed phrase was echoed back")
    r = ctx.admin.post("/api/wallets", {"name": "t_key", "kind": "paper", "nickname": "ab" * 32})
    expect_status(r, 422, "private key in nickname")


@check("wallets", "amounts are exact text; JSON numbers are refused")
def exact_amounts(ctx):
    w = ctx.make_wallet()
    r = ctx.admin.request("PUT", f"/api/wallets/{w['id']}/holdings/BTC", {"amount": 0.1})
    expect_status(r, 422, "JSON number amount")
    _hold(ctx, w["id"], "BTC", "0.10")
    expect(_amounts(ctx, w["id"]) == {"BTC": "0.1"}, "amount not normalised")


@check("wallets", "transfer moves exact amounts and is labelled simulated")
def transfer(ctx):
    a, b = ctx.make_wallet(), ctx.make_wallet()
    _hold(ctx, a["id"], "BTC", "1")
    for amount in ("0.1", "0.2"):
        r = _send(ctx.admin, a["id"], b["id"], "BTC", amount)
        expect_status(r, 201, f"send {amount}")
    expect(r.json()["label"] == "Simulated, no real funds move", "missing simulated label")
    expect(_amounts(ctx, a["id"]) == {"BTC": "0.7"}, f"source {_amounts(ctx, a['id'])}")
    expect(_amounts(ctx, b["id"]) == {"BTC": "0.3"}, f"dest {_amounts(ctx, b['id'])}")


@check("wallets", "overspending, same wallet and network mismatches are refused")
def refusals(ctx):
    a, b = ctx.make_wallet(), ctx.make_wallet()
    _hold(ctx, a["id"], "BTC", "1")
    expect_status(_send(ctx.admin, a["id"], b["id"], "BTC", "2"), 409, "more than balance")
    expect_status(_send(ctx.admin, a["id"], a["id"], "BTC", "1"), 422, "same wallet")
    eth = ctx.make_wallet("onchain", network="ethereum")
    sol = ctx.make_wallet("onchain", network="solana")
    _hold(ctx, eth["id"], "USDC", "10")
    r = _send(ctx.admin, eth["id"], sol["id"], "USDC", "1")
    expect_status(r, 409, "ethereum -> solana")
    expect("bridge" in r.text, "no explanation of why")
    r = ctx.admin.request("PUT", f"/api/wallets/{eth['id']}/holdings/BTC", {"amount": "1"})
    expect_status(r, 409, "BTC on an Ethereum wallet")


@check("wallets", "deleting a wallet with coins: refused, move_to, forced with exact name")
def delete_modes(ctx):
    a, b = ctx.make_wallet(), ctx.make_wallet()
    _hold(ctx, a["id"], "BTC", "1")
    r = ctx.admin.delete(f"/api/wallets/{a['id']}")
    expect_status(r, 409, "delete with holdings")
    expect("options" in r.json(), "no options offered")
    expect_status(
        ctx.admin.delete(f"/api/wallets/{a['id']}?move_to={b['id']}"), 204, "delete with move_to"
    )
    expect(_amounts(ctx, b["id"]) == {"BTC": "1"}, "coins weren't moved")
    expect_status(
        ctx.admin.delete(f"/api/wallets/{b['id']}?force=true&confirm_name=wrong"),
        409,
        "force with wrong name",
    )
    expect_status(
        ctx.admin.delete(
            f"/api/wallets/{b['id']}?force=true&confirm_name={ctx.created_wallets[b['id']]}"
        ),
        204,
        "force with exact name",
    )


@check("wallets", "history keeps wallet names; personal order is per user")
def history_and_order(ctx):
    a, b = ctx.make_wallet(), ctx.make_wallet()
    _hold(ctx, a["id"], "ETH", "1")
    _send(ctx.admin, a["id"], b["id"], "ETH", "1")
    rows = ctx.admin.get(f"/api/transfers?wallet_id={a['id']}").json()
    expect(
        rows and rows[0]["from_wallet_name"] == ctx.created_wallets[a["id"]],
        "history lost the wallet name",
    )
    name, _ = ctx.make_user(["wallets.view"])
    viewer = ctx.as_user(name)
    r = viewer.request("PUT", "/api/me/wallet-order", {"wallet_ids": [b["id"], a["id"]]})
    expect_status(r, 200, "viewer sets own order")
    ids = [w["id"] for w in viewer.get("/api/wallets").json()]
    expect(ids.index(b["id"]) < ids.index(a["id"]), "personal order not applied")
