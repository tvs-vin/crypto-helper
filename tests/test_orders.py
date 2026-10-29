# ruff: noqa: F811  (the exchange fakes are fixtures imported from tests/test_exchanges.py)
"""13b: placing real orders, against local fakes that check every signature the way each
exchange does. Nothing here reaches a real exchange.

- Only order calls: no module in app/orders names a call that could withdraw or move funds.
- `prepare`: sizes and prices rounded to each market's steps, protection never exceeded,
  minimums refused before sending.
- Each exchange: its market rules, a no-trade check, an immediate-or-cancel order with our own
  id, its outcome with fees, and finding an order again after the answer was lost.
"""

import base64
import hashlib
import hmac
import inspect
import json
import random
import re
import urllib.parse
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app import orders
from app.orders import Order, OrderError, Rules, TooSmall, prepare
from app.orders import binanceus as o_binance
from app.orders import coinbase as o_coinbase
from app.orders import gemini as o_gemini
from app.orders import kraken as o_kraken
from tests.test_exchanges import (  # noqa: F401  (fixtures)
    BN,
    CREDS_KR,
    GM,
    NAME,
    at,
    binance_route,
    ec_pem,
    fake,
    gemini_route,
    kr,
    kraken_auth,
)

D = Decimal

# ---- only order calls ------------------------------------------------------------------------

BANNED = re.compile(r"(?i)withdraw|transfer|deposit|convert|send|wallet|cancel|margin|futures")


@pytest.mark.parametrize("module", [o_coinbase, o_kraken, o_gemini, o_binance])
def test_order_clients_only_name_order_calls(module):
    src = inspect.getsource(module)
    paths = set(re.findall(r'"(/(?:api|0|v1|sapi)/[^"]*)"', src))
    public_or_status = {p for p in paths if p.endswith("/")}  # + an id or a market name
    assert paths - public_or_status <= module.TRADE_ENDPOINTS, paths - module.TRADE_ENDPOINTS
    for p in module.TRADE_ENDPOINTS | public_or_status:
        assert not BANNED.search(p), p
    # Every immediate-or-cancel is spelled out, and nothing rests on the book (GTC/GTD).
    assert not re.search(r"(?i)\bgtc\b|\bgtd\b|good.til", src.replace("immediate-or-cancel", ""))


# ---- prepare ---------------------------------------------------------------------------------

RULES = Rules(
    symbol="BTC-USD",
    base_step=D("0.0001"),
    base_min=D("0.0001"),
    quote_min=D("1"),
    price_step=D("0.01"),
)


def p(**kw):
    base = dict(base="BTC", quote="USD", side="buy", kind="limit", price=D("100"), spend=D("50"))
    return prepare(RULES, **{**base, **kw})


def test_a_limit_buy_never_pays_more_than_the_protection():
    o = p()
    assert o.kind == "limit" and o.limit_price == D("101.00") and o.base_size == D("0.4950")
    assert o.base_size * o.limit_price <= D("50")
    assert o.client_id.startswith("ch-") and o.symbol == "BTC-USD"


def test_a_limit_sell_never_takes_less_than_the_protection():
    o = p(side="sell", spend=None, units=D("0.123456"), price=D("100.003"))
    assert o.limit_price == D("99.01") and o.base_size == D("0.1234")  # rounded up, sized down


def test_market_orders():
    assert p(kind="market").quote_size == D("50.00")  # by money where the exchange allows
    coins = prepare(
        Rules(**{**RULES.__dict__, "market_buy_by_quote": False}),
        base="BTC",
        quote="USD",
        side="buy",
        kind="market",
        price=D("100"),
        spend=D("50"),
    )
    assert coins.base_size == D("0.4761")  # 50 / (100 x 1.05): room for the price to move
    gemini_like = Rules(**{**RULES.__dict__, "market_orders": False})
    g = prepare(
        gemini_like,
        base="BTC",
        quote="USD",
        side="buy",
        kind="market",
        price=D("100"),
        spend=D("50"),
    )
    assert g.kind == "limit" and g.limit_price == D("105.00")  # the wide band, still a limit


@pytest.mark.parametrize(
    ("kw", "words"),
    [
        ({"spend": D("0.5")}, "smallest order"),
        ({"spend": D("0.00001")}, "smallest order"),
        ({"spend": D("0")}, "Nothing to spend"),
        ({"side": "sell", "spend": None, "units": D("0.00001")}, "smallest order"),
    ],
)
def test_too_small_orders_are_refused_before_sending(kw, words):
    with pytest.raises(TooSmall, match=words):
        p(**kw)


def test_protection_holds_for_any_price_and_step():
    rng = random.Random(13)
    for _ in range(500):
        step = D(10) ** -rng.randint(0, 6)
        price = D(str(round(rng.uniform(0.001, 90000), 6)))
        pct = D(str(rng.choice([0.1, 0.5, 1, 2])))
        rules = Rules("X-USD", D("1e-8"), D("0"), D("0"), step)
        buy = prepare(
            rules,
            base="X",
            quote="USD",
            side="buy",
            kind="limit",
            price=price,
            spend=D("1000"),
            protection_pct=pct,
        )
        sell = prepare(
            rules,
            base="X",
            quote="USD",
            side="sell",
            kind="limit",
            price=price,
            units=D("1"),
            protection_pct=pct,
        )
        assert buy.limit_price <= price * (1 + pct / 100)
        assert sell.limit_price >= price * (1 - pct / 100)
        assert buy.base_size * buy.limit_price <= D("1000")


# ---- Coinbase --------------------------------------------------------------------------------


def coinbase_jwt(fake, key, method, path):
    def verify(handler):
        token = handler.headers["Authorization"].removeprefix("Bearer ")
        h, c, sig = token.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        claims = json.loads(base64.urlsafe_b64decode(pad(c)))
        raw = base64.urlsafe_b64decode(pad(sig))
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        key.public_key().verify(der, f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256()))
        assert claims["uri"] == f"{method} 127.0.0.1:{fake.port}{path}"

    return verify


@pytest.fixture
def cb(fake, at):
    from app.sync import coinbase

    at(coinbase.COINBASE)
    key, pem = ec_pem()
    fake.routes[("GET", "/api/v3/brokerage/market/products/BTC-USD")] = lambda h, b: (
        200,
        {
            "product_id": "BTC-USD",
            "base_increment": "0.00000001",
            "quote_increment": "0.01",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
            "price_increment": "0.01",
            "trading_disabled": False,
        },
    )
    return key, {"key_name": NAME, "private_key": pem}


def test_coinbase_rules_check_and_an_order(fake, cb):
    key, creds = cb
    c = o_coinbase.COINBASE_ORDERS
    rules = c.rules("BTC", "USD")
    assert rules.quote_min == D("1") and rules.price_step == D("0.01")
    order = prepare(
        rules, base="BTC", quote="USD", side="buy", kind="limit", price=D("60000"), spend=D("30")
    )
    sent = []

    def preview(h, body):
        coinbase_jwt(fake, key, "POST", "/api/v3/brokerage/orders/preview")(h)
        sent.append(json.loads(body))
        return 200, {"order_total": "30.18", "commission_total": "0.18", "errs": []}

    def create(h, body):
        coinbase_jwt(fake, key, "POST", "/api/v3/brokerage/orders")(h)
        sent.append(json.loads(body))
        return 200, {"success": True, "success_response": {"order_id": "ord-1"}}

    def status(h, body):
        coinbase_jwt(fake, key, "GET", "/api/v3/brokerage/orders/historical/ord-1")(h)
        return 200, {
            "order": {
                "status": "FILLED",
                "filled_size": "0.00049",
                "filled_value": "29.69",
                "total_fees": "0.18",
                "average_filled_price": "60600",
            }
        }

    fake.routes[("POST", "/api/v3/brokerage/orders/preview")] = preview
    fake.routes[("POST", "/api/v3/brokerage/orders")] = create
    fake.routes[("GET", "/api/v3/brokerage/orders/historical/ord-1")] = status
    assert "30.18" in c.check(creds, order)
    fill = c.place(creds, order)
    assert sent[1]["client_order_id"] == order.client_id
    assert sent[1]["order_configuration"] == {
        "sor_limit_ioc": {"base_size": "0.00049504", "limit_price": "60600"}
    }
    assert (fill.status, fill.base, fill.value, fill.fee) == (
        "filled",
        D("0.00049"),
        D("29.69"),
        D("0.18"),
    )


def test_coinbase_refusals_and_a_lost_answer(fake, cb):
    key, creds = cb
    c = o_coinbase.COINBASE_ORDERS
    order = Order("ch-x", "BTC", "USD", "buy", "market", quote_size=D("20"), symbol="BTC-USD")
    fake.routes[("POST", "/api/v3/brokerage/orders/preview")] = lambda h, b: (
        200,
        {"errs": ["PREVIEW_INSUFFICIENT_FUND"]},
    )
    with pytest.raises(OrderError, match="INSUFFICIENT_FUND"):
        c.check(creds, order)
    fake.routes[("POST", "/api/v3/brokerage/orders")] = lambda h, b: (
        200,
        {"success": False, "error_response": {"message": "Insufficient balance"}},
    )
    with pytest.raises(OrderError, match="Insufficient") as e:
        c.place(creds, order)
    assert e.value.unknown is False
    fake.routes[("POST", "/api/v3/brokerage/orders")] = lambda h, b: (502, {})
    with pytest.raises(OrderError) as e:
        c.place(creds, order)
    assert e.value.unknown is True  # may or may not have gone through: look it up


# ---- Kraken ----------------------------------------------------------------------------------


@pytest.fixture
def kro(kr, fake):
    fake.routes[("GET", "/0/public/AssetPairs")] = lambda h, b: (
        200,
        {
            "error": [],
            "result": {
                "XXBTZUSD": {
                    "altname": "XBTUSD",
                    "lot_decimals": 8,
                    "pair_decimals": 1,
                    "tick_size": "0.1",
                    "cost_decimals": 5,
                    "ordermin": "0.00005",
                    "costmin": "0.5",
                    "status": "online",
                }
            },
        },
    )
    return kr


def kraken_form(seen, result):
    def fn(h, body):
        kraken_auth(h, body)
        seen.append(dict(urllib.parse.parse_qsl(body.decode())))
        return 200, {"error": [], "result": result}

    return fn


def test_kraken_validate_order_and_lookup(kro, fake):
    k = o_kraken.KRAKEN_ORDERS
    rules = k.rules("BTC", "USD")
    assert (
        rules.symbol == "XBTUSD" and rules.base_step == D("1e-8") and not rules.market_buy_by_quote
    )
    order = prepare(
        rules, base="BTC", quote="USD", side="buy", kind="limit", price=D("60000"), spend=D("30")
    )
    seen = []
    fake.routes[("POST", "/0/private/AddOrder")] = kraken_form(seen, {"descr": {"order": "buy"}})
    assert "may trade" in k.check(CREDS_KR, order)
    assert seen[-1]["validate"] == "true" and seen[-1]["timeinforce"] == "IOC"
    assert seen[-1]["cl_ord_id"] == order.client_id and seen[-1]["price"] == "60600"
    fake.routes[("POST", "/0/private/AddOrder")] = kraken_form(seen, {"txid": ["OABCDE-12345"]})
    fake.routes[("POST", "/0/private/QueryOrders")] = kraken_form(
        seen,
        {
            "OABCDE-12345": {
                "status": "closed",
                "vol": "0.00049504",
                "vol_exec": "0.00049504",
                "cost": "29.70",
                "fee": "0.24",
                "price": "60000",
            }
        },
    )
    fill = k.place(CREDS_KR, order)
    assert "validate" not in seen[-2] and seen[-1]["txid"] == "OABCDE-12345"
    assert (fill.status, fill.value, fill.fee) == ("filled", D("29.70"), D("0.24"))
    fake.routes[("POST", "/0/private/ClosedOrders")] = kraken_form(
        seen,
        {
            "closed": {
                "OABCDE-12345": {
                    "status": "canceled",
                    "vol": "1",
                    "vol_exec": "0",
                    "cost": "0",
                    "fee": "0",
                    "cl_ord_id": order.client_id,
                }
            }
        },
    )
    assert k.lookup(CREDS_KR, order).status == "unfilled"
    assert seen[-1]["cl_ord_id"] == order.client_id


def test_kraken_never_trades_on_a_check(kro, fake):
    order = Order("ch-y", "BTC", "USD", "buy", "market", base_size=D("0.001"), symbol="XBTUSD")
    fake.routes[("POST", "/0/private/AddOrder")] = kraken_form([], {"txid": ["OOPS-1"]})
    with pytest.raises(OrderError, match="placed an order on a check"):
        o_kraken.KRAKEN_ORDERS.check(CREDS_KR, order)


# ---- Gemini ----------------------------------------------------------------------------------


def test_gemini_orders_are_ioc_limits_and_cant_be_checked(fake, at):
    from app.sync import gemini

    at(gemini.GEMINI)
    g = o_gemini.GEMINI_ORDERS
    fake.routes[("GET", "/v1/symbols/details/btcusd")] = lambda h, b: (
        200,
        {
            "symbol": "BTCUSD",
            "tick_size": 1e-08,
            "quote_increment": 0.01,
            "min_order_size": "0.00001",
            "status": "open",
        },
    )
    rules = g.rules("BTC", "USD")
    assert rules.market_orders is False and rules.base_min == D("0.00001")
    order = prepare(
        rules, base="BTC", quote="USD", side="buy", kind="market", price=D("60000"), spend=D("30")
    )
    assert order.kind == "limit" and order.limit_price == D("63000.00")
    with pytest.raises(OrderError, match="can't check"):
        g.check(GM, order)
    sent = []

    def new(h, body):
        gemini_route({}, [])(h, body)
        sent.append(json.loads(base64.b64decode(h.headers["X-GEMINI-PAYLOAD"])))
        return 200, {
            "order_id": "106817811",
            "executed_amount": "0.00047619",
            "original_amount": "0.00047619",
            "is_live": False,
        }

    def status(h, body):
        gemini_route({}, [])(h, body)
        return 200, {
            "order_id": "106817811",
            "executed_amount": "0.00047619",
            "original_amount": "0.00047619",
            "avg_execution_price": "60010",
            "is_live": False,
            "trades": [
                {
                    "amount": "0.00047619",
                    "price": "60010",
                    "fee_amount": "0.07",
                    "fee_currency": "USD",
                }
            ],
        }

    fake.routes[("POST", "/v1/order/new")] = new
    fake.routes[("POST", "/v1/order/status")] = status
    fill = g.place(GM, order)
    assert sent[0]["type"] == "exchange limit" and sent[0]["options"] == ["immediate-or-cancel"]
    assert sent[0]["client_order_id"] == order.client_id and sent[0]["price"] == "63000"
    assert fill.status == "filled" and fill.fee == D("0.07") and fill.fee_asset == "USD"


# ---- Binance.US ------------------------------------------------------------------------------


def test_binanceus_test_order_place_and_lookup(fake, at):
    from app.sync import binanceus

    at(binanceus.BINANCEUS)
    b = o_binance.BINANCEUS_ORDERS
    fake.routes[("GET", "/api/v3/exchangeInfo")] = lambda h, body: (
        200,
        {
            "symbols": [
                {
                    "symbol": "BTCUSD",
                    "status": "TRADING",
                    "quoteAssetPrecision": 2,
                    "quoteOrderQtyMarketAllowed": True,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {"filterType": "LOT_SIZE", "stepSize": "0.00001", "minQty": "0.00001"},
                        {"filterType": "NOTIONAL", "minNotional": "10"},
                    ],
                }
            ]
        },
    )
    rules = b.rules("BTC", "USD")
    assert rules.quote_min == D("10") and rules.market_buy_by_quote
    order = prepare(
        rules, base="BTC", quote="USD", side="buy", kind="market", price=D("60000"), spend=D("30")
    )
    seen = []

    def route(result):
        def fn(h, body):
            binance_route({})(h, body)
            seen.append(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(h.path).query)))
            return 200, result

        return fn

    fake.routes[("POST", "/api/v3/order/test")] = route({})
    assert "nothing traded" in b.check(BN, order)
    fake.routes[("POST", "/api/v3/order")] = route(
        {
            "orderId": 28,
            "status": "FILLED",
            "executedQty": "0.0005",
            "cummulativeQuoteQty": "29.97",
            "fills": [
                {"price": "59940", "qty": "0.0005", "commission": "0.03", "commissionAsset": "USD"}
            ],
        }
    )
    fill = b.place(BN, order)
    assert seen[-1]["quoteOrderQty"] == "30" and seen[-1]["newClientOrderId"] == order.client_id
    assert seen[-1]["type"] == "MARKET" and seen[-1]["newOrderRespType"] == "FULL"
    assert (fill.status, fill.value, fill.fee) == ("filled", D("29.97"), D("0.03"))
    fake.routes[("GET", "/api/v3/order")] = route(
        {"orderId": 28, "status": "EXPIRED", "executedQty": "0", "cummulativeQuoteQty": "0"}
    )
    assert b.lookup(BN, order).status == "unfilled"
    assert seen[-1]["origClientOrderId"] == order.client_id


# ---- the demo exchange, and the registry ----------------------------------------------------


@pytest.mark.parametrize(
    ("key", "status"), [("fine", "filled"), ("half-1", "partial"), ("nofill-1", "unfilled")]
)
def test_demo_orders(key, status):
    d = orders.client_for("demo")
    order = prepare(
        d.rules("BTC", "USD"),
        base="BTC",
        quote="USD",
        side="buy",
        kind="limit",
        price=D("60000"),
        spend=D("30"),
    )
    assert d.place({"key": key}, order).status == status


def test_a_lost_answer_is_found_again_never_resent():
    d = orders.client_for("demo")
    order = prepare(
        d.rules("BTC", "USD"),
        base="BTC",
        quote="USD",
        side="buy",
        kind="limit",
        price=D("60000"),
        spend=D("30"),
    )
    with pytest.raises(OrderError) as e:
        d.place({"key": "lost-1"}, order)
    assert e.value.unknown
    assert d.lookup({"key": "lost-1"}, order).status == "filled"


def test_every_exchange_has_an_order_client():
    from app.sync import EXCHANGES, available

    available(type("S", (), {"sync_demo": True})())  # loads every exchange
    assert set(EXCHANGES) <= {k for k in EXCHANGES if orders.client_for(k)}
    assert hmac and hashlib  # (used by the imported fakes)


def test_a_size_below_the_markets_minimum_is_refused_even_when_its_value_is_fine():
    rules = Rules("X-USD", D("0.0001"), D("0.01"), D("0"), D("0.01"))  # no value minimum
    with pytest.raises(TooSmall, match="smallest order"):
        prepare(
            rules, base="X", quote="USD", side="buy", kind="limit", price=D("100"), spend=D("0.5")
        )  # 0.0049 X, under the 0.01 minimum
    ok = prepare(
        rules, base="X", quote="USD", side="buy", kind="limit", price=D("100"), spend=D("2")
    )
    assert ok.base_size == D("0.0198")


def test_a_lookup_during_an_outage_is_unknown_never_never_arrived(fake, at):
    """13d: Gemini's lookup used to read any error as "it never reached the exchange"."""
    from app.sync import gemini

    at(gemini.GEMINI)
    order = Order("ch-z", "BTC", "USD", "buy", "limit", symbol="btcusd")
    fake.routes[("POST", "/v1/order/status")] = lambda h, b: (503, {"reason": "Maintenance"})
    with pytest.raises(OrderError) as e:
        o_gemini.GEMINI_ORDERS.lookup(GM, order)
    assert e.value.unknown
    fake.routes[("POST", "/v1/order/status")] = lambda h, b: (400, {"reason": "OrderNotFound"})
    assert o_gemini.GEMINI_ORDERS.lookup(GM, order) is None  # an answer: it never arrived


@pytest.mark.parametrize("exchange", ["kraken", "binanceus", "gemini"])
def test_a_market_lookup_during_an_outage_isnt_no_such_market(fake, at, exchange):
    """13d: a server error from the exchange used to read as "has no BTC/USD market"."""
    from app.sync import SourceError
    from app.sync import binanceus as s_binance
    from app.sync import gemini as s_gemini
    from app.sync import kraken as s_kraken

    sync = {"kraken": s_kraken.KRAKEN, "binanceus": s_binance.BINANCEUS, "gemini": s_gemini.GEMINI}
    at(sync[exchange])
    for path in ("/0/public/AssetPairs", "/api/v3/exchangeInfo", "/v1/symbols/details/btcusd"):
        fake.routes[("GET", path)] = lambda h, b: (503, {})
    client = orders.client_for(exchange)
    with pytest.raises(SourceError) as e:
        client.rules("BTC", "USD")
    assert orders.transient(e.value)
