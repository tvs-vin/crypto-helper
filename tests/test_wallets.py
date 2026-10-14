import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AuditLog
from tests.conftest import H
from tests.wallet_helpers import ETH_ADDR, SEED12, amounts, hold, user_with, wallet

# ---- permissions -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "perm"),
    [
        ("get", "/api/wallets", "wallets.view"),
        ("get", "/api/wallets/1", "wallets.view"),
        ("get", "/api/holdings/summary", "wallets.view"),
        ("get", "/api/meta/networks", "wallets.view"),
        ("post", "/api/wallets", "wallets.edit"),
        ("patch", "/api/wallets/1", "wallets.edit"),
        ("delete", "/api/wallets/1", "wallets.edit"),
        ("put", "/api/wallets/1/holdings/BTC", "wallets.edit"),
    ],
)
def test_wallet_endpoints_check_permissions(logged_in, app, method, path, perm):
    wallet(logged_in, "w1")
    others = [p for p in ("wallets.view", "wallets.edit", "prices.view") if p != perm]
    denied = user_with(
        app, logged_in, "nope", others if perm == "wallets.edit" else ["prices.view"]
    )
    kwargs = {"headers": H}
    if method in ("post", "patch", "put"):
        kwargs["json"] = {"name": "x", "kind": "paper", "amount": "1"}
    assert getattr(TestClient(app), method)(path, **kwargs).status_code == 401
    assert getattr(denied, method)(path, **kwargs).status_code == 403


def test_viewer_can_read_but_not_write(logged_in, app):
    w = wallet(logged_in, "Main")
    viewer = user_with(app, logged_in, "viewer1", ["wallets.view"])
    assert viewer.get("/api/wallets").status_code == 200
    assert (
        viewer.put(
            f"/api/wallets/{w['id']}/holdings/BTC", json={"amount": "1"}, headers=H
        ).status_code
        == 403
    )


# ---- create / read -----------------------------------------------------------------------


def test_create_onchain_wallet_full(logged_in):
    w = wallet(
        logged_in,
        "Ledger ETH",
        kind="onchain",
        network="Ethereum",
        address=ETH_ADDR,
        nickname="🦊 Long-term ETH",
        provider="Ledger",
        notes="Hardware wallet",
        tags=["Long-Term", "cold  storage", "long-term"],
    )
    assert w["network"] == "ethereum" and w["network_name"] == "Ethereum"
    assert w["display_name"] == "🦊 Long-term ETH" and w["name"] == "Ledger ETH"
    assert w["tags"] == ["long-term", "cold storage"]
    assert set(w["system_tags"]) >= {
        "kind:onchain",
        "network:ethereum",
        "provider:ledger",
        "address:yes",
        "status:empty",
    }
    assert w["colors"]["primary_is_default"] and w["colors"]["secondary_mode"] == "auto"


def test_display_name_falls_back_to_name(logged_in):
    assert wallet(logged_in, "Plain")["display_name"] == "Plain"


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"kind": "onchain"}, "need a network"),
        ({"kind": "exchange", "network": "ethereum"}, "Exchange wallets have no network"),
        (
            {
                "kind": "onchain",
                "network": "ethereum",
                "address": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
            },
            "doesn't look like a Ethereum address",
        ),
        ({"kind": "paper", "tags": ["kind:fake"]}, "built-in"),
        ({"kind": "paper", "tags": [f"t{i}" for i in range(21)]}, "at most 20 tags"),
        ({"kind": "paper", "tags": ["way too long a tag for the limit"]}, "1-24 characters"),
        ({"kind": "paper", "color_primary": "blue"}, "#RRGGBB"),
        ({"kind": "paper", "color_secondary_mode": "custom"}, "needs color_secondary"),
        ({"kind": "paper", "nickname": "x" * 65}, "at most 64"),
    ],
)
def test_create_validation(logged_in, body, fragment):
    r = logged_in.post("/api/wallets", json={"name": "W", **body}, headers=H)
    assert r.status_code == 422 and fragment in r.text, r.text


def test_twenty_tags_allowed(logged_in):
    assert len(wallet(logged_in, "Tagged", tags=[f"tag {i}" for i in range(20)])["tags"]) == 20


def test_names_unique_ignoring_case(logged_in):
    wallet(logged_in, "Main")
    r = logged_in.post("/api/wallets", json={"name": "MAIN", "kind": "paper"}, headers=H)
    assert r.status_code == 409


def test_unknown_fields_and_bad_kind_rejected(logged_in):
    assert (
        logged_in.post("/api/wallets", json={"name": "x", "kind": "bank"}, headers=H).status_code
        == 422
    )
    assert (
        logged_in.post(
            "/api/wallets", json={"name": "x", "kind": "paper", "private_key": "abc"}, headers=H
        ).status_code
        == 422
    )


# ---- the seed phrase / private key guard -------------------------------------------------


@pytest.mark.parametrize("field", ["notes", "nickname", "address", "provider", "name"])
def test_seed_phrase_refused_in_every_text_field(logged_in, app, field):
    body = {"name": "W", "kind": "paper", field: SEED12}
    r = logged_in.post("/api/wallets", json=body, headers=H)
    assert r.status_code == 422
    assert "recovery (seed) phrase" in r.text and "abandon" not in r.text  # never echoed
    with app.state.session_factory() as db:
        logged = " ".join(f"{a.action} {a.detail}" for a in db.scalars(select(AuditLog)))
    assert "abandon" not in logged


def test_tags_that_are_bip39_words_are_fine(logged_in):
    """Regression: 12+ ordinary tags that happen to be BIP39 words aren't a seed phrase."""
    tags = [
        "family",
        "travel",
        "gift",
        "school",
        "house",
        "car",
        "garden",
        "music",
        "sport",
        "office",
        "summer",
        "winter",
        "dog",
    ]
    assert len(wallet(logged_in, "Tagged", tags=tags)["tags"]) == 13


def test_private_key_refused_on_edit(logged_in):
    w = wallet(logged_in, "W")
    r = logged_in.patch(f"/api/wallets/{w['id']}", json={"notes": "key: " + "ab" * 32}, headers=H)
    assert r.status_code == 422 and "private key" in r.text


def test_validation_errors_never_echo_input(logged_in):
    r = logged_in.post(
        "/api/wallets", json={"name": "W", "kind": "paper", "notes": "s3cret-" * 1000}, headers=H
    )
    assert r.status_code == 422 and "s3cret" not in r.text


# ---- update ------------------------------------------------------------------------------


def test_patch_changes_only_what_is_sent_and_audits(logged_in, app):
    w = wallet(logged_in, "Main", nickname="Old", tags=["a"])
    r = logged_in.patch(
        f"/api/wallets/{w['id']}", json={"nickname": "New", "color_primary": "#3B82F6"}, headers=H
    )
    assert r.status_code == 200
    out = r.json()
    assert out["nickname"] == "New" and out["tags"] == ["a"]
    assert out["colors"]["primary"] == "#3b82f6" and not out["colors"]["primary_is_default"]
    with app.state.session_factory() as db:
        row = db.scalars(select(AuditLog).where(AuditLog.action == "wallet.update")).one()
    assert "colors" in row.detail and "nickname" in row.detail


def test_null_clears_optional_fields(logged_in):
    w = wallet(logged_in, "Main", nickname="Nick", color_primary="#112233")
    out = logged_in.patch(
        f"/api/wallets/{w['id']}", json={"nickname": None, "color_primary": None}, headers=H
    ).json()
    assert out["display_name"] == "Main" and out["colors"]["primary_is_default"]


def test_secondary_color_custom_and_back_to_auto(logged_in):
    w = wallet(logged_in, "Main", color_primary="#ff0000")
    out = logged_in.patch(
        f"/api/wallets/{w['id']}", json={"color_secondary": "#00ff00"}, headers=H
    ).json()
    assert out["colors"]["secondary"] == "#00ff00" and out["colors"]["secondary_mode"] == "custom"
    out = logged_in.patch(
        f"/api/wallets/{w['id']}",
        json={"color_secondary_mode": "auto", "color_scheme": "complementary"},
        headers=H,
    ).json()
    assert out["colors"]["secondary"] == "#00ffff"


def test_rename_keeps_uniqueness(logged_in):
    wallet(logged_in, "A")
    b = wallet(logged_in, "B")
    assert (
        logged_in.patch(f"/api/wallets/{b['id']}", json={"name": "a"}, headers=H).status_code == 409
    )


def test_network_change_blocked_by_holdings_it_cant_have(logged_in):
    w = wallet(logged_in, "BTC wallet", kind="onchain", network="bitcoin")
    hold(logged_in, w["id"], "BTC", "1")
    r = logged_in.patch(f"/api/wallets/{w['id']}", json={"network": "ethereum"}, headers=H)
    assert r.status_code == 409 and "WBTC" in r.text
    assert logged_in.get(f"/api/wallets/{w['id']}").json()["network"] == "bitcoin"


def test_cannot_turn_onchain_into_exchange_with_network(logged_in):
    w = wallet(logged_in, "X", kind="onchain", network="solana")
    r = logged_in.patch(f"/api/wallets/{w['id']}", json={"kind": "exchange"}, headers=H)
    assert r.status_code == 422
    r = logged_in.patch(
        f"/api/wallets/{w['id']}", json={"kind": "exchange", "network": None}, headers=H
    )
    assert r.status_code == 200 and r.json()["network"] is None


# ---- holdings ----------------------------------------------------------------------------


def test_set_update_and_remove_holding_with_audit(logged_in, app):
    w = wallet(logged_in, "Main")
    assert hold(logged_in, w["id"], "btc", "0.50")["amount"] == "0.5"
    hold(logged_in, w["id"], "BTC", "0.75")
    assert amounts(logged_in, w["id"]) == {"BTC": "0.75"}
    hold(logged_in, w["id"], "BTC", "0")
    assert amounts(logged_in, w["id"]) == {}
    with app.state.session_factory() as db:
        details = [
            r.detail
            for r in db.scalars(select(AuditLog).where(AuditLog.action == "holding.change"))
        ]
    assert details == [
        "Main (id 1) BTC: 0 -> 0.5",
        "Main (id 1) BTC: 0.5 -> 0.75",
        "Main (id 1) BTC: 0.75 -> 0",
    ]


@pytest.mark.parametrize(
    ("amount", "fragment"),
    [
        (0.5, "as text"),
        ("-1", "never negative"),
        ("1e3", "plain numbers"),
        ("0.0000000000000000001", "18 after"),
        ("1000000000000000000", "18 digits before"),
    ],
)
def test_holding_amount_rules(logged_in, amount, fragment):
    w = wallet(logged_in, "Main")
    r = logged_in.put(f"/api/wallets/{w['id']}/holdings/BTC", json={"amount": amount}, headers=H)
    assert r.status_code == 422 and fragment in r.text, r.text


@pytest.mark.parametrize("symbol", ["B", "TOOLONGSYMBOL", "BT-C", "₿"])
def test_symbol_rules(logged_in, symbol):
    w = wallet(logged_in, "Main")
    r = logged_in.put(f"/api/wallets/{w['id']}/holdings/{symbol}", json={"amount": "1"}, headers=H)
    assert r.status_code in (404, 422)


def test_coin_must_exist_on_wallet_network(logged_in):
    w = wallet(logged_in, "ETH wallet", kind="onchain", network="ethereum")
    r = logged_in.put(f"/api/wallets/{w['id']}/holdings/BTC", json={"amount": "1"}, headers=H)
    assert r.status_code == 409 and "WBTC" in r.text
    hold(logged_in, w["id"], "USDC", "100")  # USDC does exist on Ethereum
    hold(logged_in, w["id"], "PEPE", "1000")  # unknown coins are allowed
    hold(logged_in, w["id"], "BTC", "0")  # setting zero is always fine


def test_archived_wallet_is_read_only_for_money(logged_in):
    w = wallet(logged_in, "Old")
    hold(logged_in, w["id"], "BTC", "1")
    logged_in.patch(f"/api/wallets/{w['id']}", json={"archived": True}, headers=H)
    r = logged_in.put(f"/api/wallets/{w['id']}/holdings/BTC", json={"amount": "2"}, headers=H)
    assert r.status_code == 409 and "archived" in r.text
    out = logged_in.patch(f"/api/wallets/{w['id']}", json={"nickname": "still editable"}, headers=H)
    assert out.status_code == 200 and "status:archived" in out.json()["system_tags"]


def test_summary_totals_by_coin(logged_in):
    a, b, c = wallet(logged_in, "A"), wallet(logged_in, "B"), wallet(logged_in, "C")
    hold(logged_in, a["id"], "BTC", "0.1")
    hold(logged_in, b["id"], "BTC", "0.2")
    hold(logged_in, b["id"], "ETH", "3")
    hold(logged_in, c["id"], "BTC", "5")
    logged_in.patch(f"/api/wallets/{c['id']}", json={"archived": True}, headers=H)
    s = logged_in.get("/api/holdings/summary").json()
    assert s == [
        {"symbol": "BTC", "total": "0.3", "wallets": 2},
        {"symbol": "ETH", "total": "3", "wallets": 1},
    ]
    s = logged_in.get("/api/holdings/summary?include_archived=true").json()
    assert s[0] == {"symbol": "BTC", "total": "5.3", "wallets": 3}


# ---- listing, filters, order -------------------------------------------------------------


def test_filters_and_tags(logged_in):
    a = wallet(logged_in, "Alpha", kind="exchange", provider="Coinbase", tags=["savings"])
    b = wallet(logged_in, "Beta", kind="onchain", network="solana")
    hold(logged_in, b["id"], "SOL", "2")
    wallet(logged_in, "Gamma", tags=["savings"])
    ids = lambda q: [w["id"] for w in logged_in.get(f"/api/wallets{q}").json()]  # noqa: E731
    assert ids("?kind=exchange") == [a["id"]]
    assert ids("?network=solana") == [b["id"]]
    assert len(ids("?tag=savings")) == 2
    assert ids("?tag=coin:sol") == [b["id"]]  # built-in tags filter too
    assert ids("?tag=provider:coinbase") == [a["id"]]


def test_archived_hidden_by_default(logged_in):
    a = wallet(logged_in, "A")
    wallet(logged_in, "B")
    logged_in.patch(f"/api/wallets/{a['id']}", json={"archived": True}, headers=H)
    assert [w["name"] for w in logged_in.get("/api/wallets").json()] == ["B"]
    assert [w["name"] for w in logged_in.get("/api/wallets?archived=true").json()] == ["A"]
    assert len(logged_in.get("/api/wallets?archived=all").json()) == 2


def test_personal_order_is_per_user(logged_in, app):
    a, b, c = (wallet(logged_in, n) for n in ("A", "B", "C"))
    r = logged_in.put("/api/me/wallet-order", json={"wallet_ids": [c["id"], a["id"]]}, headers=H)
    assert r.status_code == 200
    names = [w["name"] for w in logged_in.get("/api/wallets").json()]
    assert names == ["C", "A", "B"]  # unlisted wallets follow, by name
    other = user_with(app, logged_in, "bob", ["wallets.view"])
    assert [w["name"] for w in other.get("/api/wallets").json()] == ["A", "B", "C"]
    assert (
        other.put("/api/me/wallet-order", json={"wallet_ids": [b["id"]]}, headers=H).status_code
        == 200
    )  # no wallets.edit needed
    assert [w["name"] for w in logged_in.get("/api/wallets").json()] == ["C", "A", "B"]


def test_order_rejects_unknown_ids(logged_in):
    r = logged_in.put("/api/me/wallet-order", json={"wallet_ids": [999]}, headers=H)
    assert r.status_code == 422


def test_meta_networks(logged_in):
    data = logged_in.get("/api/meta/networks").json()
    assert data["networks"]["ethereum"] == "Ethereum" and "bitcoin" in data["coin_networks"]["BTC"]
    assert data["max_tags"] == 20 and data["simulated_label"] == "Simulated, no real funds move"
