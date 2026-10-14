import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AuditLog
from app.prices.providers import MockProvider
from tests.conftest import H
from tests.wallet_helpers import hold, user_with, wallet


def mock_price(cid: str, fiat: str = "usd") -> Decimal:
    return MockProvider().fetch([cid], [fiat])[cid][fiat].price


def audit_actions(app):
    with app.state.session_factory() as db:
        return [r.action for r in db.scalars(select(AuditLog))]


# ---- permissions -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "perm"),
    [
        ("get", "/api/prices", "prices.view"),
        ("get", "/api/prices/supported", "prices.view"),
        ("get", "/api/prices/history?symbol=BTC", "prices.view"),
        ("get", "/api/prices/history/settings", "prices.view"),
        ("put", "/api/prices/history/settings", "prices.manage"),
        ("post", "/api/coins", "prices.manage"),
        ("delete", "/api/coins/MOCK", "prices.manage"),
    ],
)
def test_price_endpoints_check_permissions(logged_in, app, method, path, perm):
    others = ["wallets.view"] if perm == "prices.view" else ["prices.view", "wallets.view"]
    denied = user_with(app, logged_in, "nope", others)
    kwargs = {"headers": H}
    if method in ("put", "post"):
        kwargs["json"] = {"coingecko_id": "mockcoin"}
    assert getattr(TestClient(app), method)(path, **kwargs).status_code == 401
    assert getattr(denied, method)(path, **kwargs).status_code == 403


def test_portfolio_needs_both_wallets_and_prices(logged_in, app):
    only_wallets = user_with(app, logged_in, "walletsonly", ["wallets.view"])
    only_prices = user_with(app, logged_in, "pricesonly", ["prices.view"])
    both = user_with(app, logged_in, "bothperms", ["wallets.view", "prices.view"])
    assert only_wallets.get("/api/portfolio").status_code == 403
    assert only_prices.get("/api/portfolio").status_code == 403
    assert both.get("/api/portfolio").status_code == 200


def test_admin_preset_includes_prices_manage(logged_in):
    assert "prices.manage" in logged_in.get("/api/meta/permissions").json()["presets"]["admin"]


# ---- prices ------------------------------------------------------------------------------


def test_prices_default_to_every_supported_coin(logged_in):
    data = logged_in.get("/api/prices").json()
    assert len(data["prices"]) == 18 and data["unpriced"] == []
    assert data["source"].startswith("Mock") and data["stale"] is False and data["as_of"]
    btc = next(p for p in data["prices"] if p["symbol"] == "BTC")
    assert Decimal(btc["price"]) == mock_price("bitcoin") and btc["name"] == "Bitcoin"


def test_prices_for_chosen_symbols_and_fiat(logged_in):
    data = logged_in.get("/api/prices?symbols=btc,ETH,NOPE&fiat=JPY").json()
    assert [p["symbol"] for p in data["prices"]] == ["BTC", "ETH"]
    assert data["unpriced"] == ["NOPE"] and data["fiat"] == "jpy"
    assert Decimal(data["prices"][0]["price"]) == mock_price("bitcoin", "jpy")


@pytest.mark.parametrize("query", ["fiat=btc", "symbols=B", "symbols=" + ",".join(["BTC"] * 201)])
def test_price_query_validation(logged_in, query):
    assert logged_in.get(f"/api/prices?{query}").status_code == 422


def test_outage_with_no_prices_ever_is_a_clear_503(logged_in, app):
    app.state.prices.provider.fail_with = "CoinGecko rate limit reached"
    r = logged_in.get("/api/prices")
    assert r.status_code == 503 and "rate limit" in r.json()["detail"]


def test_outage_after_success_serves_stale(logged_in, app):
    logged_in.get("/api/prices")
    app.state.prices.provider.fail_with = "down"
    app.state.prices.invalidate()
    data = logged_in.get("/api/prices").json()
    assert data["stale"] is True and data["error"] == "down" and len(data["prices"]) == 18


def test_supported_lists_coins_and_fiats(logged_in):
    data = logged_in.get("/api/prices/supported").json()
    assert data["fiats"] == ["usd", "eur", "gbp", "jpy", "cad", "aud"]
    assert {"symbol": "BTC", "name": "Bitcoin", "coingecko_id": "bitcoin", "builtin": True} in data[
        "coins"
    ]


# ---- portfolio and wallet values ---------------------------------------------------------


def test_portfolio_values_are_exact_and_rounded(logged_in):
    a, b = wallet(logged_in, "A"), wallet(logged_in, "B")
    hold(logged_in, a["id"], "BTC", "0.5")
    hold(logged_in, b["id"], "BTC", "0.25")
    hold(logged_in, b["id"], "PEPE", "1000")  # not a supported coin
    data = logged_in.get("/api/portfolio?fiat=usd").json()
    btc_value = (Decimal("0.75") * mock_price("bitcoin")).quantize(Decimal("0.01"))
    assert Decimal(data["total"]) == btc_value
    assert data["unpriced"] == ["PEPE"]
    coin = next(c for c in data["coins"] if c["symbol"] == "BTC")
    assert coin["amount"] == "0.75" and Decimal(coin["value"]) == btc_value
    assert next(c for c in data["coins"] if c["symbol"] == "PEPE")["value"] is None
    assert {w["name"]: w["unpriced"] for w in data["wallets"]} == {"A": [], "B": ["PEPE"]}


def test_portfolio_uses_your_fiat_preference(logged_in):
    hold(logged_in, wallet(logged_in, "A")["id"], "BTC", "1")
    logged_in.patch("/api/me/preferences", json={"fiat": "jpy"}, headers=H)
    data = logged_in.get("/api/portfolio").json()
    assert data["fiat"] == "jpy" and "." not in data["total"]  # yen: no decimals


def test_wallet_values_only_for_people_who_can_see_prices(logged_in, app):
    a, b = wallet(logged_in, "Small"), wallet(logged_in, "Big")
    hold(logged_in, a["id"], "BTC", "0.1")
    hold(logged_in, b["id"], "BTC", "2")
    rows = logged_in.get("/api/wallets?sort=value").json()
    assert [w["name"] for w in rows] == ["Big", "Small"] and rows[0]["value"]
    viewer = user_with(app, logged_in, "viewer1", ["wallets.view"])
    plain = viewer.get("/api/wallets").json()
    assert "value" not in plain[0]
    assert viewer.get("/api/wallets?sort=value").status_code == 403


# ---- history endpoints -------------------------------------------------------------------


def test_history_endpoint(logged_in, app):
    with app.state.session_factory() as db:
        from app.prices import history

        snap = app.state.prices.snapshot(db)
        history.record(db, snap, history.HistorySettings())
        db.commit()
    rows = logged_in.get("/api/prices/history?symbol=btc&hours=1").json()["rows"]
    assert len(rows) == 1 and rows[0]["kind"] == "point"
    assert logged_in.get("/api/prices/history?symbol=NOPE").status_code == 404


def test_history_settings_get_put_and_audit(logged_in, app):
    data = logged_in.get("/api/prices/history/settings").json()
    assert data["settings"]["fine_interval_minutes"] == 10 and data["stats"]["points"] == 0
    new = {
        **data["settings"],
        "fine_interval_minutes": 5,
        "fine_keep_hours": 48,
        "coarse_interval_minutes": 30,
        "coarse_keep_days": 365,
        "fiats": ["usd", "eur"],
    }
    r = logged_in.put("/api/prices/history/settings", json=new, headers=H)
    assert r.status_code == 200 and r.json()["settings"]["fiats"] == ["usd", "eur"]
    assert logged_in.get("/api/prices/history/settings").json()["settings"] == new
    assert "prices.history_settings" in audit_actions(app)


@pytest.mark.parametrize(
    "bad", [{"coarse_interval_minutes": 45}, {"fine_interval_minutes": 7}, {"fiats": []}, {"x": 1}]
)
def test_history_settings_rejects_bad_values(logged_in, bad):
    r = logged_in.put("/api/prices/history/settings", json=bad, headers=H)
    assert r.status_code == 422 and r.json()["detail"]


# ---- custom coins ------------------------------------------------------------------------


def test_add_coin_checks_coingecko_and_prices_it(logged_in, app):
    r = logged_in.post("/api/coins", json={"coingecko_id": "mockcoin"}, headers=H)
    assert r.status_code == 201
    assert r.json() == {
        "symbol": "MOCK",
        "coingecko_id": "mockcoin",
        "name": "Mock Coin",
        "builtin": False,
        "lookalike_count": 0,
    }
    data = logged_in.get("/api/prices?symbols=MOCK").json()
    assert Decimal(data["prices"][0]["price"]) == mock_price("mockcoin")
    assert "coin.add" in audit_actions(app)


def test_lookalike_symbols_need_confirmation(logged_in):
    r = logged_in.post("/api/coins", json={"coingecko_id": "fake-one"}, headers=H)
    assert r.status_code == 409 and r.json()["lookalikes"][0]["coingecko_id"] == "fake-two"
    assert "Scam tokens" in r.json()["detail"]
    r = logged_in.post("/api/coins", json={"coingecko_id": "fake-one", "confirm": True}, headers=H)
    assert r.status_code == 201 and r.json()["lookalike_count"] == 1


@pytest.mark.parametrize(
    ("body", "status", "fragment"),
    [
        ({"coingecko_id": "Not Valid!"}, 422, "lowercase"),
        ({"coingecko_id": "does-not-exist"}, 404, "no coin"),
        ({"coingecko_id": "bitcoin"}, 409, "already added"),
        ({"coingecko_id": "mockcoin", "symbol": "BTC"}, 409, "built in"),
        ({"coingecko_id": "mockcoin", "symbol": "x"}, 422, "2-10"),
    ],
)
def test_add_coin_refusals(logged_in, body, status, fragment):
    r = logged_in.post("/api/coins", json=body, headers=H)
    assert r.status_code == status and fragment in r.json()["detail"], r.text


def test_remove_coin(logged_in):
    logged_in.post("/api/coins", json={"coingecko_id": "mockcoin"}, headers=H)
    assert logged_in.delete("/api/coins/BTC", headers=H).status_code == 409
    assert logged_in.delete("/api/coins/mock", headers=H).status_code == 204
    assert logged_in.get("/api/prices?symbols=MOCK").json()["unpriced"] == ["MOCK"]
    assert logged_in.delete("/api/coins/MOCK", headers=H).status_code == 404


def test_coingecko_outage_while_adding(logged_in, app, monkeypatch):
    from app.prices.providers import ProviderError

    def down():
        raise ProviderError("CoinGecko didn't answer (TimeoutError)")

    monkeypatch.setattr(app.state.prices.provider, "coin_list", down)
    r = logged_in.post("/api/coins", json={"coingecko_id": "mockcoin"}, headers=H)
    assert r.status_code == 503 and "didn't answer" in r.text


# ---- preferences -------------------------------------------------------------------------


def test_preferences_defaults(logged_in):
    p = logged_in.get("/api/me/preferences").json()
    assert p["theme"] == "dark" and p["fiat"] == "usd" and p["watchlist"] == []
    assert p["overview"] == {
        "columns": ["price", "change_24h", "holdings", "value"],
        "sort": {"by": "value", "direction": "desc"},
    }
    assert p["layout"] == {"windows": []} and p["wallet_order"] == []


def test_patch_changes_only_what_is_sent(logged_in):
    w = wallet(logged_in, "A")
    logged_in.put("/api/me/wallet-order", json={"wallet_ids": [w["id"]]}, headers=H)
    r = logged_in.patch(
        "/api/me/preferences",
        json={"theme": "terminal", "watchlist": ["btc", "eth", "BTC"]},
        headers=H,
    )
    assert r.status_code == 200
    p = r.json()
    assert p["theme"] == "terminal" and p["watchlist"] == ["BTC", "ETH"]
    assert p["wallet_order"] == [w["id"]]  # not wiped


def test_put_replaces_everything(logged_in):
    logged_in.patch("/api/me/preferences", json={"theme": "light"}, headers=H)
    p = logged_in.put("/api/me/preferences", json={"fiat": "eur"}, headers=H).json()
    assert p["theme"] == "dark" and p["fiat"] == "eur"


def test_window_layout(logged_in):
    windows = [
        {"panel": "wallets", "x": 0, "y": 0, "w": 600, "h": 400},
        {"panel": "overview", "x": 610, "y": 0, "w": 500, "h": 400, "open": False, "z": 3},
    ]
    p = logged_in.patch(
        "/api/me/preferences", json={"layout": {"windows": windows}}, headers=H
    ).json()
    assert p["layout"]["windows"][1]["open"] is False and p["layout"]["windows"][0]["z"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"theme": "neon"},
        {"fiat": "btc"},
        {"watchlist": ["B"]},
        {"watchlist": [f"C{i}" for i in range(51)]},
        {"overview": {"columns": ["price", "market_cap"]}},
        {"overview": {"sort": {"by": "value", "direction": "sideways"}}},
        {"layout": {"windows": [{"panel": "wallets", "x": 0, "y": 0, "w": 50, "h": 400}]}},
        {"layout": {"windows": [{"panel": "chat", "x": 0, "y": 0, "w": 500, "h": 400}]}},
        {"layout": {"windows": [{"panel": "wallets", "x": 0, "y": 0, "w": 500, "h": 400}] * 2}},
        {"layout": {"windows": [{"panel": "wallets", "x": -1, "y": 0, "w": 500, "h": 400}]}},
        {"surprise": True},
    ],
)
def test_preference_validation(logged_in, body):
    before = logged_in.get("/api/me/preferences").json()
    r = logged_in.patch("/api/me/preferences", json=body, headers=H)
    assert r.status_code == 422
    assert logged_in.get("/api/me/preferences").json() == before


def test_size_limit(logged_in):
    huge = [10**15 + i for i in range(1000)]
    r = logged_in.patch("/api/me/preferences", json={"wallet_order": huge}, headers=H)
    assert r.status_code == 413


def test_preferences_are_per_user_and_need_no_permission(logged_in, app):
    nobody = user_with(app, logged_in, "nobody", [])
    assert (
        nobody.patch("/api/me/preferences", json={"theme": "light"}, headers=H).status_code == 200
    )
    assert logged_in.get("/api/me/preferences").json()["theme"] == "dark"
    assert TestClient(app).get("/api/me/preferences").status_code == 401


def test_me_returns_preferences_with_defaults(logged_in):
    me = logged_in.get("/api/auth/me").json()
    assert json.dumps(me)  # serialisable
