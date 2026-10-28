"""Gemini orders. Gemini's API has no market orders ("because they provide you with no price
protection"): every order is an `exchange limit` order with `immediate-or-cancel`, and a
"market" order is one a few percent away (Rules.market_orders = False). There's no way to check
an order without trading. `client_order_id` on every order; `order/status` finds it again and
lists its trades (with their fees)."""

import re

from app.orders import Fill, Order, OrderClient, OrderError, Rules, num, register
from app.sync import SourceError, http
from app.sync.gemini import GEMINI
from app.sync.http import amount

TRADE_ENDPOINTS = {
    "/v1/order/new",
    "/v1/order/status",  # reading: an order's outcome, by its id or ours
}
DETAILS = "/v1/symbols/details/"  # + btcusd (public)
SYMBOL_RE = re.compile(r"^[a-z0-9]{5,16}$")


class GeminiOrders(OrderClient):
    exchange = GEMINI
    can_check = False

    def _call(self, creds, path, **params):
        assert path in TRADE_ENDPOINTS
        return self.exchange.signed_call(creds, path, **params)

    def rules(self, base: str, quote: str) -> Rules:
        symbol = f"{base}{quote}".lower()
        if not SYMBOL_RE.match(symbol):
            raise OrderError("That isn't a market name")
        try:
            d = http.call("Gemini", "GET", self.exchange.base + DETAILS + symbol)
        except SourceError:
            raise OrderError(f"Gemini has no {base}/{quote} market") from None
        if not isinstance(d, dict) or str(d.get("symbol", "")).lower() != symbol:
            raise OrderError(f"Gemini has no {base}/{quote} market")
        if d.get("status") not in (None, "open"):
            raise OrderError(f"Gemini's {base}/{quote} market is {d.get('status')}")
        return Rules(
            symbol=symbol,
            base_step=amount(d["tick_size"]),  # Gemini: the size step is called tick_size
            base_min=amount(d["min_order_size"]),
            quote_min=amount("0"),
            price_step=amount(d["quote_increment"]),
            market_orders=False,
        )

    def check(self, creds: dict, order: Order) -> str:
        raise OrderError("Gemini can't check an order without placing it")

    def _outcome(self, order: Order, o: dict) -> Fill:
        base = amount(o.get("executed_amount") or "0")
        original = amount(o.get("original_amount") or "0")
        trades = o.get("trades") or []
        fee = sum((amount(t.get("fee_amount") or "0") for t in trades), amount("0"))
        fee_asset = str((trades[0] if trades else {}).get("fee_currency") or order.quote).upper()
        value = sum((amount(t["amount"]) * amount(t["price"]) for t in trades), amount("0"))
        avg = o.get("avg_execution_price")
        if not trades and base > 0 and avg:
            value = base * amount(avg)
        status = (
            "filled" if base > 0 and base >= original else "partial" if base > 0 else "unfilled"
        )
        if o.get("is_live"):
            raise OrderError("Gemini still shows the order as live", unknown=True)
        return Fill(
            str(o.get("order_id")),
            order.client_id,
            status,
            base,
            value,
            fee,
            fee_asset,
            amount(avg) if avg and base > 0 else None,
        )

    def place(self, creds: dict, order: Order) -> Fill:
        o = self._send(
            lambda: self._call(
                creds,
                "/v1/order/new",
                symbol=order.symbol,
                amount=num(order.base_size),
                price=num(order.limit_price),
                side=order.side,
                type="exchange limit",
                options=["immediate-or-cancel"],
                client_order_id=order.client_id,
            )
        )
        if not isinstance(o, dict) or "order_id" not in o:
            raise OrderError("Gemini didn't say which order it made", unknown=True)
        full = self._call(creds, "/v1/order/status", order_id=o["order_id"], include_trades=True)
        return self._outcome(order, full if isinstance(full, dict) else o)

    def lookup(self, creds: dict, order: Order) -> Fill | None:
        try:
            o = self._call(
                creds, "/v1/order/status", client_order_id=order.client_id, include_trades=True
            )
        except SourceError:
            return None  # Gemini doesn't know the id: it never arrived
        if isinstance(o, list):  # by client id, Gemini answers with a list
            o = o[0] if o else None
        return self._outcome(order, o) if isinstance(o, dict) else None


GEMINI_ORDERS = register("gemini", GeminiOrders())
