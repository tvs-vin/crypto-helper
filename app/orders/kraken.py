"""Kraken orders (spot REST API). `AddOrder` with `timeinforce=IOC` for limit orders; market
orders fill at once by nature. `validate=true` checks an order without trading, which also shows
the key may trade (Kraken can't report that otherwise). Every order carries `cl_ord_id`, so an
order whose outcome is unknown is found again with `ClosedOrders`."""

import re
import time

from app.orders import Fill, Order, OrderClient, OrderError, Rules, num, register, transient
from app.sync import SourceError, http
from app.sync.http import amount
from app.sync.kraken import KRAKEN

TRADE_ENDPOINTS = {
    "/0/private/AddOrder",
    "/0/private/QueryOrders",  # reading: an order's outcome
    "/0/private/ClosedOrders",  # reading: an order by our id
}
PAIR_RE = re.compile(r"^[A-Z0-9]{4,16}$")
TXID_RE = re.compile(r"^[A-Z0-9-]{6,40}$")
DONE = {"closed", "canceled", "expired"}


class KrakenOrders(OrderClient):
    exchange = KRAKEN

    def _call(self, creds, path, params):
        assert path in TRADE_ENDPOINTS
        return self.exchange.signed_call(creds, path, params=params)

    def rules(self, base: str, quote: str) -> Rules:
        to_kraken = {v: k for k, v in self.exchange.aliases.items()}  # BTC -> XBT
        wanted = f"{to_kraken.get(base.upper(), base.upper())}{quote.upper()}"
        if not PAIR_RE.match(wanted):
            raise OrderError("That isn't a market name")
        url = f"{self.exchange.base}/0/public/AssetPairs?pair={wanted}"
        try:
            result = self.exchange._result(http.call("Kraken", "GET", url))
        except SourceError as e:
            if transient(e):  # the exchange couldn't be reached: not an answer about the market
                raise
            raise OrderError(f"Kraken has no {base}/{quote} market") from None
        if not result:
            raise OrderError(f"Kraken has no {base}/{quote} market")
        p = next(iter(result.values()))
        if p.get("status", "online") != "online":
            raise OrderError(f"Kraken's {base}/{quote} market is {p.get('status')}")
        tick = p.get("tick_size") or f"1e-{int(p['pair_decimals'])}"
        return Rules(
            symbol=str(p.get("altname") or wanted),
            base_step=amount(f"1e-{int(p['lot_decimals'])}"),
            base_min=amount(p.get("ordermin") or "0"),
            quote_min=amount(p.get("costmin") or "0"),
            price_step=amount(tick),
            quote_step=amount(f"1e-{int(p.get('cost_decimals', 2))}"),
            market_buy_by_quote=False,  # Kraken sizes orders in coins
        )

    @staticmethod
    def _params(order: Order) -> dict:
        p = {
            "pair": order.symbol,
            "type": order.side,
            "ordertype": order.kind,
            "volume": num(order.base_size),
            "cl_ord_id": order.client_id,
        }
        if order.kind == "limit":
            p.update(price=num(order.limit_price), timeinforce="IOC")
        return p

    def check(self, creds: dict, order: Order) -> str:
        try:
            r = self._call(
                creds, "/0/private/AddOrder", {**self._params(order), "validate": "true"}
            )
        except SourceError as e:
            raise OrderError(str(e), final=e.final) from None
        if (r or {}).get("txid"):  # validate must never place one
            raise OrderError("Kraken placed an order on a check!", unknown=True)
        what = ((r or {}).get("descr") or {}).get("order", "the order")
        return f"Kraken would take it ({what}); the key may trade"

    def _outcome(self, order: Order, txid: str, o: dict) -> Fill:
        base = amount(o.get("vol_exec") or "0")
        vol = amount(o.get("vol") or "0")
        status = "filled" if base > 0 and base >= vol else "partial" if base > 0 else "unfilled"
        avg = o.get("price")
        return Fill(
            txid,
            order.client_id,
            status,
            base,
            amount(o.get("cost") or "0"),
            amount(o.get("fee") or "0"),
            order.quote,
            amount(avg) if avg and base > 0 else None,
        )

    def _wait(self, creds: dict, order: Order, txid: str, wait: float = 10) -> Fill:
        deadline = time.monotonic() + wait
        while True:
            r = self._call(creds, "/0/private/QueryOrders", {"txid": txid})
            o = (r or {}).get(txid) or {}
            if o.get("status") in DONE:
                return self._outcome(order, txid, o)
            if time.monotonic() > deadline:
                raise OrderError(f"Kraken still shows the order as {o.get('status')}", unknown=True)
            time.sleep(0.5)

    def place(self, creds: dict, order: Order) -> Fill:
        r = self._send(lambda: self._call(creds, "/0/private/AddOrder", self._params(order)))
        txids = (r or {}).get("txid") or []
        if len(txids) != 1 or not TXID_RE.match(str(txids[0])):
            raise OrderError("Kraken didn't say which order it made", unknown=True)
        return self._wait(creds, order, str(txids[0]))

    def lookup(self, creds: dict, order: Order) -> Fill | None:
        r = self._call(creds, "/0/private/ClosedOrders", {"cl_ord_id": order.client_id})
        for txid, o in ((r or {}).get("closed") or {}).items():
            if o.get("cl_ord_id") in (None, order.client_id) and TXID_RE.match(str(txid)):
                return self._outcome(order, str(txid), o)
        return None


KRAKEN_ORDERS = register("kraken", KrakenOrders())
