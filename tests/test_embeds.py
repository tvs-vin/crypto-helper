"""Embeds: managed in the main app, served by the separate embed-only app."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.config import Settings
from app.embeds.server import create_embed_app
from app.main import create_app
from app.models import AuditLog, Embed, User
from tests.conftest import PASSWORD, H


@pytest.fixture
def pair(tmp_path):
    """The main app (signed in as super, with two wallets) and the embed app on one DB."""
    url = f"sqlite:///{tmp_path}/e.db"
    # Both read the same config in real life, including the public embed address.
    main = create_app(
        Settings(database_url=url, _env_file=None, embed_public_url="https://embed.example.com")
    )
    with TestClient(main) as c:
        c.post(
            "/api/setup", json={"token": main.state.setup_token, "password": PASSWORD}, headers=H
        )
        c.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
        a = c.post(
            "/api/wallets",
            json={
                "name": "Ledger BTC",
                "nickname": "Cold <b>storage</b>",
                "kind": "onchain",
                "network": "bitcoin",
                "tags": ["long-term"],
            },
            headers=H,
        ).json()
        b = c.post("/api/wallets", json={"name": "Coinbase", "kind": "exchange"}, headers=H).json()
        c.put(f"/api/wallets/{a['id']}/holdings/BTC", json={"amount": "1.2345"}, headers=H)
        c.put(f"/api/wallets/{b['id']}/holdings/ETH", json={"amount": "9.876"}, headers=H)
        embed_app = create_embed_app(
            Settings(database_url=url, _env_file=None, embed_public_url="https://embed.example.com")
        )
        with TestClient(embed_app) as e:
            yield c, e, main, {"a": a, "b": b}


def make(c, kind="portfolio", **options):
    r = c.post(
        "/api/embeds", json={"name": "My stack", "kind": kind, "options": options}, headers=H
    )
    assert r.status_code == 201, r.text
    return r.json()


def path(embed):
    return "/embed/" + embed["url"].rsplit("/embed/", 1)[1]


# ---- managing ----------------------------------------------------------------------------


def test_meta_marks_amounts_and_values_sensitive_and_off(pair):
    c, *_ = pair
    items = c.get("/api/embeds/meta").json()["items"]
    assert items["amounts"] == {"default": False, "label": "Amounts held", "sensitive": True}
    assert items["values"]["default"] is False and items["values"]["sensitive"]
    assert all(v["default"] for k, v in items.items() if k not in ("amounts", "values"))


def test_link_token_is_never_stored_in_plain(pair):
    c, _, main, _ = pair
    em = make(c)
    token = em["url"].rsplit("/", 1)[1]
    assert em["url"].startswith("https://embed.example.com/embed/") and len(token) >= 32
    with main.state.session_factory() as db:
        row = db.get(Embed, em["id"])
    assert token not in row.token_hash and token not in row.token_encrypted


def test_needs_the_permission_and_only_your_own(pair):
    c, _, main, _ = pair
    em = make(c)
    c.post(
        "/api/users",
        json={
            "username": "bob",
            "password": "bob-password-123",
            "permissions": ["wallets.view", "embeds.create"],
        },
        headers=H,
    )
    c.post(
        "/api/users",
        json={"username": "carl", "password": "carl-password-123", "permissions": ["wallets.view"]},
        headers=H,
    )
    bob, carl = TestClient(main), TestClient(main)
    bob.post("/api/auth/login", json={"username": "bob", "password": "bob-password-123"}, headers=H)
    carl.post(
        "/api/auth/login", json={"username": "carl", "password": "carl-password-123"}, headers=H
    )
    assert carl.get("/api/embeds").status_code == 403
    assert bob.get("/api/embeds").json() == []
    assert bob.delete(f"/api/embeds/{em['id']}", headers=H).status_code == 404


@pytest.mark.parametrize(
    "options",
    [
        {"allowed_origins": ["javascript:alert(1)"]},
        {"items": {"secret_keys": True}},
        {"theme": "../x"},
        {"fiat": "btc"},
        {"refresh_seconds": 5},
    ],
)
def test_bad_options_refused(pair, options):
    c, *_ = pair
    r = c.post(
        "/api/embeds", json={"name": "x", "kind": "portfolio", "options": options}, headers=H
    )
    assert r.status_code == 422


def test_audited_and_sensitive_items_called_out(pair):
    c, _, main, _ = pair
    make(c, items={"amounts": True})
    with main.state.session_factory() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "embed.create"))
    assert "shows amounts" in row.detail


# ---- what the embed shows ----------------------------------------------------------------


def test_default_portfolio_shows_shares_but_no_amounts_or_values(pair):
    c, e, *_ = pair
    r = e.get(path(make(c)))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "BTC" in html and "ETH" in html and "%" in html
    assert "1.2345" not in html and "9.876" not in html  # amounts are off by default
    assert 'class="total"' not in html and 'class="value"' not in html
    assert '<meta property="og:image" content="https://embed.example.com/embed/' in html
    assert "<script" not in html


def test_turning_on_amounts_and_values(pair):
    c, e, *_ = pair
    html = e.get(path(make(c, items={"amounts": True, "values": True}))).text
    assert "1.2345" in html and "9.876" in html and 'class="total"' in html


@pytest.mark.parametrize(
    ("item", "kind", "gone"),
    [
        ("coins", "portfolio", "BTC"),
        ("prices", "prices", 'class="price"'),
        ("change_24h", "prices", 'class="change'),
        ("percent", "portfolio", 'class="pct"'),
        ("wallet_names", "wallets", "Coinbase"),  # (a wallet without a nickname)
        ("tags", "wallets", "long-term"),
        ("network", "wallets", "bitcoin"),
        ("title", "portfolio", "<h1>"),
        ("updated", "portfolio", "<time"),
    ],
)
def test_each_switch_hides_its_item(pair, item, kind, gone):
    c, e, *_ = pair
    shown = e.get(path(make(c, kind))).text
    hidden = e.get(path(make(c, kind, items={item: False}))).text
    assert gone in shown and gone not in hidden


def test_text_is_escaped(pair):
    c, e, *_ = pair
    html = e.get(path(make(c, "wallets"))).text
    assert "Cold &lt;b&gt;storage&lt;/b&gt;" in html and "<b>storage" not in html


def test_scope_to_some_wallets_and_coins(pair):
    c, e, _, w = pair
    html = e.get(path(make(c, "wallets", wallet_ids=[w["b"]["id"]]))).text
    assert "Coinbase" in html and "Ledger" not in html
    prices = e.get(path(make(c, "prices", symbols=["SOL", "DOGE"]))).text
    assert "SOL" in prices and "DOGE" in prices and "BTC" not in prices


# ---- framing rules -----------------------------------------------------------------------


def test_no_framing_unless_sites_are_listed(pair):
    c, e, *_ = pair
    r = e.get(path(make(c)))
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    r = e.get(path(make(c, allowed_origins=["https://blog.example.com"])))
    assert "frame-ancestors https://blog.example.com" in r.headers["content-security-policy"]
    assert "x-frame-options" not in r.headers
    assert "script-src" not in r.headers["content-security-policy"]  # default-src 'none'


# ---- when an embed stops working ---------------------------------------------------------


def test_disabled_expired_rotated_and_deleted_links_404(pair):
    c, e, *_ = pair
    em = make(c)
    assert e.get(path(em)).status_code == 200
    c.patch(f"/api/embeds/{em['id']}", json={"enabled": False}, headers=H)
    assert e.get(path(em)).status_code == 404
    c.patch(
        f"/api/embeds/{em['id']}",
        json={
            "enabled": True,
            "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        },
        headers=H,
    )
    assert e.get(path(em)).status_code == 404
    c.patch(f"/api/embeds/{em['id']}", json={"expires_at": None}, headers=H)
    new = c.post(f"/api/embeds/{em['id']}/rotate", headers=H).json()
    assert e.get(path(em)).status_code == 404 and e.get(path(new)).status_code == 200
    c.delete(f"/api/embeds/{em['id']}", headers=H)
    assert e.get(path(new)).status_code == 404
    assert e.get("/embed/not-a-real-token").text == e.get(path(new)).text == "Not found"


def test_owner_deactivated_or_losing_permission_turns_it_off(pair):
    c, e, main, _ = pair
    c.post(
        "/api/users",
        json={
            "username": "maker",
            "password": "maker-password-1",
            "permissions": ["wallets.view", "prices.view", "embeds.create"],
        },
        headers=H,
    )
    maker = TestClient(main)
    maker.post(
        "/api/auth/login", json={"username": "maker", "password": "maker-password-1"}, headers=H
    )
    em = make(maker)
    assert e.get(path(em)).status_code == 200
    uid = next(u["id"] for u in c.get("/api/users").json() if u["username"] == "maker")
    c.patch(f"/api/users/{uid}", json={"permissions": ["embeds.create", "prices.view"]}, headers=H)
    assert e.get(path(em)).status_code == 404  # lost wallets.view
    c.patch(f"/api/users/{uid}", json={"permissions": ["embeds.create", "wallets.view"]}, headers=H)
    html = e.get(path(em)).text  # back, but without prices.view nothing price-based shows
    assert "%" not in html and 'class="price"' not in html and "BTC" in html
    c.patch(f"/api/users/{uid}", json={"is_active": False}, headers=H)
    assert e.get(path(em)).status_code == 404


def test_views_are_counted(pair):
    c, e, main, _ = pair
    em = make(c)
    for _ in range(3):
        e.get(path(em))
    assert c.get("/api/embeds").json()[0]["views"] == 3


# ---- the image and the stylesheet --------------------------------------------------------


def test_preview_image(pair):
    c, e, *_ = pair
    em = make(c)
    r = e.get(path(em) + ".png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (1200, 630)
    assert e.get("/embed/nope.png").status_code == 404
    p = c.get(f"/api/embeds/{em['id']}/preview.png")  # the same image, from the main app
    assert p.status_code == 200 and Image.open(io.BytesIO(p.content)).size == (1200, 630)


def test_theme_stylesheet_and_private_themes(pair):
    c, e, main, _ = pair
    css = e.get(path(make(c, theme="terminal")) + ".css").text
    assert "--accent: #3BE36A;" in css
    with main.state.session_factory() as db:  # someone else's private theme: falls back
        from app.models import UserTheme

        other = User(username="ann", password_hash="x", permissions=[])
        db.add(other)
        db.flush()
        t = UserTheme(owner_id=other.id, name="Private", data={"colors": {}}, published=False)
        db.add(t)
        db.commit()
        tid = t.id
    css = e.get(path(make(c, theme=f"custom:{tid}")) + ".css").text
    assert "--accent: #7545FC;" in css


# ---- the embed server is nothing else ----------------------------------------------------


@pytest.mark.parametrize(
    "p",
    [
        "/",
        "/api/auth/me",
        "/api/setup/status",
        "/docs",
        "/openapi.json",
        "/static/js/main.js",
        "/embed-assets/../config.py",
        "/embed-assets/nope.css",
    ],
)
def test_embed_server_has_no_other_routes(pair, p):
    _, e, *_ = pair
    assert e.get(p).status_code == 404


def test_embed_server_refuses_writes(pair):
    _, e, *_ = pair
    for r in (e.post("/api/auth/login", json={}), e.delete("/embed/x"), e.put("/embed/x")):
        # Refused by the server's own guard, before any route: plain text, locked-down headers.
        assert r.status_code == 405 and r.text == "Method not allowed"
        assert "default-src 'none'" in r.headers["content-security-policy"]


def test_embed_assets(pair):
    _, e, *_ = pair
    assert e.get("/embed-assets/embed.css").status_code == 200
    assert e.get("/embed-assets/fonts/inter.woff2").content[:4] == b"wOF2"


def test_rate_limit_and_network_allowlist(tmp_path, pair):
    c, _, main, _ = pair
    em = make(c)
    url = main.state.settings.database_url
    limited = create_embed_app(Settings(database_url=url, _env_file=None, embed_rate_per_minute=5))
    with TestClient(limited) as e:
        codes = [e.get(path(em)).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    fenced = create_embed_app(
        Settings(database_url=url, _env_file=None, embed_allowed_networks="127.0.0.0/8")
    )
    with TestClient(fenced, client=("203.0.113.5", 1)) as e:
        assert e.get(path(em)).status_code == 403


def test_fiat_text_formatting():
    from app.embeds.page import fiat

    assert fiat("369.9", "usd") == "$369.90"
    assert fiat("-1234.5", "eur") == "-€1,234.50"
    assert fiat("0.000123", "usd") == "$0.000123"
    assert fiat("1500", "jpy") == "¥1,500"
