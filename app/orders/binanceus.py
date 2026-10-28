"""Binance.US orders. `LIMIT` with `timeInForce=IOC`, or `MARKET` (buys sized in money with
`quoteOrderQty` where the market allows it). `order/test` checks an order without trading.
`newClientOrderId` on every order; `GET order` by it finds an order whose outcome is unknown,
and `myTrades` gives its fees."""

import re

from app.orders import Fill, Order, OrderClient, OrderError, Rules, num, register
from app.sync import SourceError, http
from app.sync.binanceus import BINANCEUS
from app.sync.http import amount

TRADE_ENDPOINTS = {
    "/api/v3/order",  # POST: place; GET: an order's outcome by our id
    "/api/v3/order/test",
    "/api/v3/myTrades",  # reading: an order's fees
}
SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,16}$")
DONE = {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}


class BinanceUSOrders(OrderClient):
    exchange = BINANCEUS

    def _call(self, creds, method, path, params):
        assert path in TRADE_ENDPOINTS
        return self.exchange.signed_call(creds, method, path, params=params)

    def rules(self, base: str, quote: str) -> Rules:
        symbol = f"{base}{quote}".upper()
        if not SYMBOL_RE.match(symbol):
            raise OrderError("That isn't a market name")
        try:
            info = http.call(
                "Binance.US", "GET", f"{self.exchange.base}/api/v3/exchangeInfo?symbol={symbol}"
            )
        except SourceError:
            raise OrderError(f"Binance.US has no {base}/{quote} market") from None
        s = next((x for x in (info or {}).get("symbols", []) if x.get("symbol") == symbol), None)
        if s is None:
            raise OrderError(f"Binance.US has no {base}/{quote} market")
        if s.get("status") != "TRADING":
            raise OrderError(f"Binance.US's {symbol} market is {s.get('status')}")
        f = {x["filterType"]: x for x in s.get("filters", [])}
        notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
        return Rules(
            symbol=symbol,
            base_step=amount(f["LOT_SIZE"]["stepSize"]),
            base_min=amount(f["LOT_SIZE"]["minQty"]),
            quote_min=amount(notional.get("minNotional") or "0"),
            price_step=amount(f["PRICE_FILTER"]["tickSize"]),
            quote_step=amount(f"1e-{int(s.get('quoteAssetPrecision', 2))}"),
            market_buy_by_quote=bool(s.get("quoteOrderQtyMarketAllowed")),
        )

    @staticmethod
    def _params(order: Order) -> dict:
        p = {
            "symbol": order.symbol,
            "side": order.side.upper(),
            "type": order.kind.upper(),
            "newClientOrderId": order.client_id,
            "newOrderRespType": "FULL",
        }
        if order.kind == "limit":
            p.update(timeInForce="IOC", quantity=num(order.base_size), price=num(order.limit_price))
        elif order.quote_size is not None:
            p["quoteOrderQty"] = num(order.quote_size)
        else:
            p["quantity"] = num(order.base_size)
        return p

    def check(self, creds: dict, order: Order) -> str:
        try:
            self._call(creds, "POST", "/api/v3/order/test", self._params(order))
        except SourceError as e:
            raise OrderError(f"Binance.US wouldn't take it: {e}", final=e.final) from None
        return "Binance.US would take it (a test order: nothing traded)"

    def _outcome(self, creds: dict, order: Order, o: dict) -> Fill:
        if o.get("status") not in DONE:
            raise OrderError(f"Binance.US still shows the order as {o.get('status')}", unknown=True)
        base = amount(o.get("executedQty") or "0")
        value = amount(o.get("cummulativeQuoteQty") or "0")
        fills = o.get("fills")
        if fills is None and base > 0:  # looked up afterwards: the fees are in its trades
            fills = self._call(
                creds, "GET", "/api/v3/myTrades", {"symbol": order.symbol, "orderId": o["orderId"]}
            )
            fills = [
                {"commission": t.get("commission"), "commissionAsset": t.get("commissionAsset")}
                for t in fills or []
            ]
        fills = fills or []
        fee = sum((amount(x.get("commission") or "0") for x in fills), amount("0"))
        fee_asset = str((fills[0] if fills else {}).get("commissionAsset") or order.quote).upper()
        status = "filled" if o.get("status") == "FILLED" else "partial" if base > 0 else "unfilled"
        return Fill(
            str(o.get("orderId")),
            order.client_id,
            status,
            base,
            value,
            fee,
            fee_asset,
            value / base if base > 0 else None,
        )

    def place(self, creds: dict, order: Order) -> Fill:
        o = self._send(lambda: self._call(creds, "POST", "/api/v3/order", self._params(order)))
        if not isinstance(o, dict) or "orderId" not in o:
            raise OrderError("Binance.US didn't say which order it made", unknown=True)
        return self._outcome(creds, order, o)

    def lookup(self, creds: dict, order: Order) -> Fill | None:
        try:
            o = self._call(
                creds,
                "GET",
                "/api/v3/order",
                {"symbol": order.symbol, "origClientOrderId": order.client_id},
            )
        except SourceError as e:
            if "Order does not exist" in str(e):
                return None
            raise OrderError(str(e)) from None
        return self._outcome(creds, order, o)


BINANCEUS_ORDERS = register("binanceus", BinanceUSOrders())
