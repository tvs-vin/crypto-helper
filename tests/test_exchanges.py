"""11b: the four exchange clients, against a local fake exchange that checks every signature the
way the real one does (and the published signing examples, for the maths itself)."""

import base64
import hashlib
import hmac
import http.server
import json
import threading
import urllib.parse
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app.sync import SourceError, binanceus, coinbase, gemini, kraken
from app.sync import http as sync_http
from tests.conftest import H


class Fake:
    """A tiny exchange: `routes[(method, path)] = fn(handler, body) -> (status, json)`."""

    def __init__(self):
        self.routes, self.seen = {}, []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _go(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                path = urllib.parse.urlsplit(self.path).path
                fake.seen.append((method, path))
                fn = fake.routes.get((method, path))
                status, payload = fn(self, body) if fn else (404, {"message": "no such path"})
                if status in (301, 302):
                    self.send_response(status)
                    self.send_header("Location", f"{fake.url}/target")  # here: seen if followed
                    self.end_headers()
                    return
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._go("GET")

            def do_POST(self):
                self._go("POST")

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_port
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.srv.shutdown()


@pytest.fixture
def at(fake, monkeypatch):
    """Point an exchange client at the fake."""

    def point(client):
        monkeypatch.setattr(client, "base", fake.url)
        if isinstance(client, coinbase.Coinbase):
            monkeypatch.setattr(client, "host", f"127.0.0.1:{fake.port}")
        return client

    return point


# ---- the signing maths (published examples) --------------------------------------------------


def test_kraken_signature_matches_krakens_example():
    secret = (
        "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="
    )
    body = "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25"
    assert kraken.sign("/0/private/AddOrder", body, "1616492376594", secret) == (
        "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ=="
    )


def test_binance_signature_matches_binances_example():
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    query = (
        "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
        "&recvWindow=5000&timestamp=1499827319559"
    )
    assert binanceus.sign(query, secret) == (
        "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"
    )


# ---- read-only by construction --------------------------------------------------------------

ALLOWED = {
    "coinbase": {"/api/v3/brokerage/key_permissions", "/api/v3/brokerage/accounts"},
    "kraken": {"/0/public/Assets", "/0/private/BalanceEx", "/0/private/WithdrawMethods"},
    "gemini": {"/v1/roles", "/v1/balances"},
    "binanceus": {"/sapi/v1/account/apiRestrictions", "/api/v3/account"},
}


@pytest.mark.parametrize("module", [coinbase, kraken, gemini, binanceus])
def test_clients_only_contain_reading_calls(module):
    """Nothing that could place an order or move funds is even in the code. (Kraken's
    WithdrawMethods only lists methods: it's how a key that may withdraw is caught.)"""
    import inspect
    import re

    name = module.__name__.rsplit(".", 1)[1]
    src = inspect.getsource(module)
    paths = set(re.findall(r'"(/(?:api|0|v1|sapi)/[^"]*[^"/])"', src))  # full paths, not prefixes
    assert paths <= ALLOWED[name], paths - ALLOWED[name]
    assert module.READ_ENDPOINTS == ALLOWED[name]
    banned = re.compile(r"(?i)order|cancel|withdraw(?!methods)|transfer|convert|/v1/order")
    for p in module.READ_ENDPOINTS:
        assert not banned.search(p), p


# ---- Coinbase --------------------------------------------------------------------------------


def ec_pem(key=None):
    key = key or ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    return key, pem


NAME = "organizations/0b1c2d3e-aaaa/apiKeys/9f8e7d6c-bbbb"


def coinbase_auth(fake, key, expect_path):
    """Check the JWT the way Coinbase does: ES256 signature, claims, the right uri."""

    def verify(handler):
        token = handler.headers["Authorization"].removeprefix("Bearer ")
        h, c, sig = token.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        header = json.loads(base64.urlsafe_b64decode(pad(h)))
        claims = json.loads(base64.urlsafe_b64decode(pad(c)))
        raw = base64.urlsafe_b64decode(pad(sig))
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        key.public_key().verify(der, f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256()))
        assert header["alg"] == "ES256" and header["kid"] == NAME and header["nonce"]
        assert claims["sub"] == NAME and claims["iss"] == "cdp"
        assert claims["exp"] - claims["nbf"] == 120
        assert claims["uri"] == f"GET 127.0.0.1:{fake.port}{expect_path}"

    return verify


def test_coinbase_read_only_key(fake, at):
    cb = at(coinbase.COINBASE)
    key, pem = ec_pem()
    creds = {"key_name": NAME, "private_key": pem}
    check_auth = coinbase_auth(fake, key, "/api/v3/brokerage/key_permissions")

    def perms(h, _):
        check_auth(h)
        return 200, {
            "can_view": True,
            "can_trade": False,
            "can_transfer": False,
            "portfolio_uuid": "x",
            "portfolio_type": "DEFAULT",
        }

    fake.routes[("GET", "/api/v3/brokerage/key_permissions")] = perms
    result = cb.check(creds)
    assert result.read_only is True and "Coinbase" in result.summary
    fake.routes[("GET", "/api/v3/brokerage/key_permissions")] = lambda h, b: (
        200,
        {"can_view": True, "can_trade": True, "can_transfer": False},
    )
    assert cb.check(creds).read_only is False
    fake.routes[("GET", "/api/v3/brokerage/key_permissions")] = lambda h, b: (
        200,
        {"can_view": True, "can_trade": False, "can_transfer": True},
    )
    assert cb.check(creds).read_only is False


def test_coinbase_balances_across_pages(fake, at):
    cb = at(coinbase.COINBASE)
    key, pem = ec_pem()
    check_auth = coinbase_auth(fake, key, "/api/v3/brokerage/accounts")
    pages = {
        "": {
            "accounts": [
                {
                    "currency": "BTC",
                    "available_balance": {"value": "0.12345678", "currency": "BTC"},
                    "hold": {"value": "0.00000001", "currency": "BTC"},
                },
                {
                    "currency": "USD",
                    "available_balance": {"value": "10.50", "currency": "USD"},
                    "hold": {"value": "0", "currency": "USD"},
                },
            ],
            "has_next": True,
            "cursor": "abc-123",
        },
        "abc-123": {
            "accounts": [
                {
                    "currency": "ETH",
                    "available_balance": {"value": "1.000000000000000001", "currency": "ETH"},
                    "hold": {"value": "0", "currency": "ETH"},
                },
                {
                    "currency": "SOL",
                    "available_balance": {"value": "0", "currency": "SOL"},
                    "hold": {"value": "0", "currency": "SOL"},
                },
            ],
            "has_next": False,
            "cursor": "",
        },
    }

    def accounts(h, _):
        check_auth(h)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query)
        assert q["limit"] == ["250"]
        return 200, pages[q.get("cursor", [""])[0]]

    fake.routes[("GET", "/api/v3/brokerage/accounts")] = accounts
    got = cb.fetch({"key_name": NAME, "private_key": pem}).balances
    assert got == {
        "BTC": Decimal("0.12345679"),
        "USD": Decimal("10.50"),
        "ETH": Decimal("1.000000000000000001"),
    }


def test_coinbase_key_problems_are_explained():
    _, pem = ec_pem()
    with pytest.raises(SourceError, match="organizations/"):
        coinbase.COINBASE.check({"key_name": "nope", "private_key": pem})
    with pytest.raises(SourceError, match="isn't a PEM key"):
        coinbase.COINBASE.check({"key_name": NAME, "private_key": "hello"})
    ed = ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    with pytest.raises(SourceError, match="ECDSA") as e:
        coinbase.COINBASE.check({"key_name": NAME, "private_key": ed.decode()})
    assert e.value.final
    # A key pasted on one line with \n escapes (as some downloads show it) works too.
    _, pem = ec_pem()
    coinbase.COINBASE._key({"key_name": NAME, "private_key": pem.replace("\n", "\\n")})


# ---- Kraken ----------------------------------------------------------------------------------

KR_SECRET = base64.b64encode(b"k" * 64).decode()


def kraken_auth(handler, body: bytes):
    """Check API-Sign the way Kraken does."""
    form = urllib.parse.parse_qs(body.decode())
    nonce = form["nonce"][0]
    path = urllib.parse.urlsplit(handler.path).path
    digest = hashlib.sha256((nonce + body.decode()).encode()).digest()
    expected = base64.b64encode(
        hmac.new(base64.b64decode(KR_SECRET), path.encode() + digest, hashlib.sha512).digest()
    ).decode()
    assert handler.headers["API-Sign"] == expected and handler.headers["API-Key"] == "kr-key"
    return int(nonce)


@pytest.fixture
def kr(fake, at):
    k = at(kraken.KRAKEN)
    k._assets = None
    nonces = []

    def private(result):
        def fn(h, body):
            nonces.append(kraken_auth(h, body))
            return 200, result

        return fn

    fake.routes[("GET", "/0/public/Assets")] = lambda h, b: (
        200,
        {
            "error": [],
            "result": {
                "XXBT": {"altname": "XBT"},
                "XETH": {"altname": "ETH"},
                "ZUSD": {"altname": "USD"},
                "DOT.S": {"altname": "DOT.S"},
                "XXDG": {"altname": "XDG"},
            },
        },
    )
    fake.routes[("POST", "/0/private/BalanceEx")] = private(
        {
            "error": [],
            "result": {
                "XXBT": {"balance": "0.5000000000", "hold_trade": "0.1"},
                "XETH": {"balance": "2.25", "hold_trade": "0"},
                "DOT.S": {"balance": "10", "hold_trade": "0"},
                "DOT": {"balance": "1.5", "hold_trade": "0"},
                "XXDG": {"balance": "100", "hold_trade": "0"},
                "ZUSD": {"balance": "12.34", "hold_trade": "0"},
            },
        }
    )
    fake.routes[("POST", "/0/private/WithdrawMethods")] = private(
        {"error": ["EGeneral:Permission denied"]}
    )
    k.nonces, k.private_route = nonces, private
    return k


CREDS_KR = {"key": "kr-key", "secret": KR_SECRET}


def test_kraken_balances_with_its_asset_names(kr):
    got = kr.fetch(CREDS_KR).balances
    # Totals, not just what's free; staked DOT counts as DOT; XBT and XDG keep Kraken's names
    # here (the exchange's aliases turn them into BTC and DOGE when applied).
    assert got == {
        "XBT": Decimal("0.5"),
        "ETH": Decimal("2.25"),
        "DOT": Decimal("11.5"),
        "XDG": Decimal("100"),
        "USD": Decimal("12.34"),
    }
    assert kraken.KRAKEN.aliases == {"XBT": "BTC", "XDG": "DOGE"}


def test_kraken_check(kr, fake):
    result = kr.check(CREDS_KR)
    assert result.read_only is None and "can't withdraw" in result.summary  # trading: confirm
    # A key that may withdraw: WithdrawMethods answers, so it's refused.
    fake.routes[("POST", "/0/private/WithdrawMethods")] = kr.private_route(
        {"error": [], "result": [{"asset": "XXBT", "method": "Bitcoin"}]}
    )
    assert kr.check(CREDS_KR).read_only is False
    # Nonces only go up.
    assert kr.nonces == sorted(set(kr.nonces))


def test_kraken_errors(kr, fake):
    fake.routes[("POST", "/0/private/BalanceEx")] = kr.private_route(
        {"error": ["EAPI:Invalid key"]}
    )
    with pytest.raises(SourceError, match="refused the key") as e:
        kr.fetch(CREDS_KR)
    assert e.value.final
    fake.routes[("POST", "/0/private/BalanceEx")] = kr.private_route(
        {"error": ["EGeneral:Permission denied"]}
    )
    with pytest.raises(SourceError, match="Funds → Query"):
        kr.check(CREDS_KR)
    fake.routes[("POST", "/0/private/BalanceEx")] = kr.private_route(
        {"error": ["EAPI:Rate limit exceeded"]}
    )
    with pytest.raises(SourceError) as e:
        kr.fetch(CREDS_KR)
    assert not e.value.final
    with pytest.raises(SourceError, match="base64"):
        kr.fetch({"key": "kr-key", "secret": "not base64 !!"})


# ---- Gemini ----------------------------------------------------------------------------------


def gemini_route(result, seen):
    def fn(h, body):
        payload = h.headers["X-GEMINI-PAYLOAD"].encode()
        assert (
            h.headers["X-GEMINI-SIGNATURE"]
            == hmac.new(b"gm-secret", payload, hashlib.sha384).hexdigest()
        )
        data = json.loads(base64.b64decode(payload))
        assert data["request"] == urllib.parse.urlsplit(h.path).path and body == b""
        seen.append(int(data["nonce"]))
        return 200, result

    return fn


GM = {"key": "account-abc", "secret": "gm-secret"}


@pytest.mark.parametrize(
    "roles, expect",
    [
        ({"isAuditor": True, "isTrader": False, "isFundManager": False}, True),
        ({"isAuditor": False, "isTrader": True, "isFundManager": False}, False),
        ({"isAuditor": False, "isTrader": False, "isFundManager": True}, False),
        ({"counterparty_id": "x"}, None),
    ],
)
def test_gemini_roles(fake, at, roles, expect):
    g, seen = at(gemini.GEMINI), []
    fake.routes[("POST", "/v1/roles")] = gemini_route(roles, seen)
    assert g.check(GM).read_only is expect


def test_gemini_balances(fake, at):
    g, seen = at(gemini.GEMINI), []
    fake.routes[("POST", "/v1/balances")] = gemini_route(
        [
            {"type": "exchange", "currency": "BTC", "amount": "1.5", "available": "1.0"},
            {"type": "exchange", "currency": "USD", "amount": "0", "available": "0"},
            {"type": "exchange", "currency": "eth", "amount": "0.000000000000000001"},
        ],
        seen,
    )
    assert g.fetch(GM).balances == {"BTC": Decimal("1.5"), "ETH": Decimal("1E-18")}


# ---- Binance.US ------------------------------------------------------------------------------


def binance_route(result, status=200):
    def fn(h, _):
        q = urllib.parse.urlsplit(h.path).query
        unsigned, _, sig = q.rpartition("&signature=")
        assert sig == hmac.new(b"bn-secret", unsigned.encode(), hashlib.sha256).hexdigest()
        assert "timestamp=" in unsigned and h.headers["X-MBX-APIKEY"] == "bn-key"
        return status, result

    return fn


BN = {"key": "bn-key", "secret": "bn-secret"}


def test_binanceus_check(fake, at):
    b = at(binanceus.BINANCEUS)
    fake.routes[("GET", "/api/v3/account")] = binance_route({"balances": []})
    # Not answered on Binance.US: the account answers, so the key works; confirm the rest.
    assert b.check(BN).read_only is None
    fake.routes[("GET", "/sapi/v1/account/apiRestrictions")] = binance_route(
        {"enableReading": True, "enableWithdrawals": False, "enableSpotAndMarginTrading": False}
    )
    assert b.check(BN).read_only is True
    fake.routes[("GET", "/sapi/v1/account/apiRestrictions")] = binance_route(
        {"enableReading": True, "enableSpotAndMarginTrading": True}
    )
    assert b.check(BN).read_only is False
    fake.routes[("GET", "/sapi/v1/account/apiRestrictions")] = binance_route(
        {"enableReading": True, "enableWithdrawals": True}
    )
    assert b.check(BN).read_only is False


def test_binanceus_balances_and_a_bad_key(fake, at):
    b = at(binanceus.BINANCEUS)
    fake.routes[("GET", "/api/v3/account")] = binance_route(
        {
            "canTrade": True,
            "balances": [
                {"asset": "BTC", "free": "0.10000000", "locked": "0.05000000"},
                {"asset": "USD", "free": "0.00", "locked": "0.00"},
            ],
        }
    )
    assert b.fetch(BN).balances == {"BTC": Decimal("0.15")}
    fake.routes[("GET", "/api/v3/account")] = binance_route(
        {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."}, status=401
    )
    with pytest.raises(SourceError, match="Invalid API-key") as e:
        b.check(BN)
    assert e.value.final


# ---- the shared HTTP rules -------------------------------------------------------------------


def test_http_rules(fake):
    fake.routes[("GET", "/r")] = lambda h, b: (302, {})
    fake.routes[("GET", "/target")] = lambda h, b: (200, {"ok": True})
    fake.routes[("GET", "/slow")] = lambda h, b: (429, {})
    fake.routes[("GET", "/bad")] = lambda h, b: (200, b"<html>")
    with pytest.raises(SourceError):
        sync_http.call("X", "GET", fake.url + "/r")  # redirects aren't followed
    assert fake.seen == [("GET", "/r")]
    with pytest.raises(SourceError, match="slow down") as e:
        sync_http.call("X", "GET", fake.url + "/slow")
    assert not e.value.final
    with pytest.raises(SourceError, match="isn't JSON"):
        sync_http.call("X", "GET", fake.url + "/bad")
    with pytest.raises(SourceError, match="Couldn't reach"):
        sync_http.call("X", "GET", "http://127.0.0.1:1/x")


# ---- end to end: through the API and the sync engine -----------------------------------------


def test_a_gemini_wallet_syncs_through_the_app(fake, at, logged_in):
    at(gemini.GEMINI)
    seen = []
    fake.routes[("POST", "/v1/roles")] = gemini_route(
        {"isAuditor": True, "isTrader": False, "isFundManager": False}, seen
    )
    fake.routes[("POST", "/v1/balances")] = gemini_route(
        [
            {"type": "exchange", "currency": "BTC", "amount": "0.25"},
            {"type": "exchange", "currency": "GUSD", "amount": "5"},
        ],
        seen,
    )
    r = logged_in.post(
        "/api/connections",
        json={"kind": "gemini", "label": "My Gemini", "credentials": GM},
        headers=H,
    )
    assert r.status_code == 201, r.text
    assert r.json()["check_summary"] == "Auditor (read-only), checked with Gemini"
    w = logged_in.post(
        "/api/wallets", json={"name": "Gemini", "kind": "exchange"}, headers=H
    ).json()
    logged_in.put(
        f"/api/wallets/{w['id']}/source",
        json={"kind": "exchange", "connection_id": r.json()["id"]},
        headers=H,
    )
    out = logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()
    assert out["ok"], out
    holdings = logged_in.get(f"/api/wallets/{w['id']}").json()["holdings"]
    assert [(h["symbol"], h["amount"]) for h in holdings] == [("BTC", "0.25")]
    assert out["sync"]["untracked"] == [{"asset": "GUSD", "amount": "5"}]
    # The roles are checked again before every sync.
    assert seen and fake.seen.count(("POST", "/v1/roles")) == 2


def test_a_trading_key_is_refused_through_the_app(fake, at, logged_in, app):
    at(gemini.GEMINI)
    fake.routes[("POST", "/v1/roles")] = gemini_route({"isTrader": True}, [])
    r = logged_in.post(
        "/api/connections", json={"kind": "gemini", "label": "x", "credentials": GM}, headers=H
    )
    assert r.status_code == 422 and "can trade or move funds" in r.json()["detail"]
    assert "gm-secret" not in r.text
