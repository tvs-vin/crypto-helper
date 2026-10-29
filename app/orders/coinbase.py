"""Coinbase orders (Advanced Trade API). Limit orders are `sor_limit_ioc`, market orders
`market_market_ioc`: immediate-or-cancel either way. `orders/preview` checks an order without
trading. Coinbase treats a repeated `client_order_id` as the same order, so looking an order up
after a network failure is asking for it again with the same id (documented by Coinbase)."""

import re
import time

from app.orders import Fill, Order, OrderClient, OrderError, Rules, num, register
from app.sync import SourceError, http
from app.sync.coinbase import COINBASE
from app.sync.http import amount

TRADE_ENDPOINTS = {
    "/api/v3/brokerage/orders",
    "/api/v3/brokerage/orders/preview",
}
ORDER_STATUS = "/api/v3/brokerage/orders/historical/"  # + an order id (reading)
PRODUCT = "/api/v3/brokerage/market/products/"  # + BTC-USD (public)
ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
DONE = {"FILLED", "CANCELLED", "EXPIRED", "FAILED"}


class CoinbaseOrders(OrderClient):
    exchange = COINBASE

    def _call(self, creds, method, path, body=None):
        assert path in TRADE_ENDPOINTS or (method == "GET" and path.startswith(ORDER_STATUS))
        return self.exchange.signed_call(creds, method, path, body=body)

    def rules(self, base: str, quote: str) -> Rules:
        product = f"{base}-{quote}".upper()
        if not ID_RE.match(product):
            raise OrderError("That isn't a market name")
        p = http.call("Coinbase", "GET", self.exchange.base + PRODUCT + product)
        if not isinstance(p, dict) or p.get("product_id") != product:
            raise OrderError(f"Coinbase has no {product} market")
        if p.get("trading_disabled") or p.get("is_disabled"):
            raise OrderError(f"Trading {product} is switched off on Coinbase")
        return Rules(
            symbol=product,
            base_step=amount(p["base_increment"]),
            base_min=amount(p["base_min_size"]),
            quote_min=amount(p["quote_min_size"]),
            price_step=amount(p["price_increment"]),
            quote_step=amount(p["quote_increment"]),
        )

    @staticmethod
    def _config(order: Order) -> dict:
        if order.kind == "limit":
            return {
                "sor_limit_ioc": {
                    "base_size": num(order.base_size),
                    "limit_price": num(order.limit_price),
                }
            }
        size = (
            {"quote_size": num(order.quote_size)}
            if order.quote_size is not None
            else {"base_size": num(order.base_size)}
        )
        return {"market_market_ioc": size}

    def check(self, creds: dict, order: Order) -> str:
        body = {
            "product_id": order.symbol,
            "side": order.side.upper(),
            "order_configuration": self._config(order),
        }
        try:
            r = self._call(creds, "POST", "/api/v3/brokerage/orders/preview", body)
        except SourceError as e:
            raise OrderError(str(e), final=e.final) from None
        errs = (r or {}).get("errs") or []
        if errs:
            raise OrderError(f"Coinbase wouldn't take it: {', '.join(map(str, errs))[:160]}")
        total = r.get("order_total") or "?"
        fee = r.get("commission_total") or "?"
        return f"Coinbase would take it: {total} {order.quote} in all, {fee} of it fees"

    def _create(self, creds: dict, order: Order) -> str:
        body = {
            "client_order_id": order.client_id,
            "product_id": order.symbol,
            "side": order.side.upper(),
            "order_configuration": self._config(order),
        }
        r = self._send(lambda: self._call(creds, "POST", "/api/v3/brokerage/orders", body))
        if not (r or {}).get("success"):
            why = ((r or {}).get("error_response") or {}).get("message") or "refused"
            raise OrderError(f"Coinbase didn't take the order: {str(why)[:160]}")
        order_id = str((r.get("success_response") or {}).get("order_id", ""))
        if not ID_RE.match(order_id):
            raise OrderError("Coinbase sent an order id the app doesn't understand", unknown=True)
        return order_id

    def _status(self, creds: dict, order: Order, order_id: str, wait: float = 10) -> Fill:
        """An immediate-or-cancel order ends within moments: wait for it to say how."""
        deadline = time.monotonic() + wait
        while True:
            r = self._call(creds, "GET", ORDER_STATUS + order_id)
            o = (r or {}).get("order") or {}
            if o.get("status") in DONE or time.monotonic() > deadline:
                break
            time.sleep(0.5)
        base = amount(o.get("filled_size") or "0")
        value = amount(o.get("filled_value") or "0")
        status = "filled" if o.get("status") == "FILLED" else "partial" if base > 0 else "unfilled"
        if o.get("status") not in DONE:
            raise OrderError(f"Coinbase still shows the order as {o.get('status')}", unknown=True)
        avg = o.get("average_filled_price")
        return Fill(
            order_id,
            order.client_id,
            status,
            base,
            value,
            amount(o.get("total_fees") or "0"),
            order.quote,
            amount(avg) if avg and base > 0 else None,
        )

    def place(self, creds: dict, order: Order) -> Fill:
        return self._status(creds, order, self._create(creds, order))

    def lookup(self, creds: dict, order: Order) -> Fill | None:
        # The same client_order_id again: Coinbase answers with the order it already has (or
        # takes it now if the first never arrived; either way there's exactly one).
        return self.place(creds, order)


COINBASE_ORDERS = register("coinbase", CoinbaseOrders())
