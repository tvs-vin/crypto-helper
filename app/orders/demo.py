"""The demo exchange's orders (BOT_SYNC_DEMO=true only): no network, made-up fills. The key's
first word decides what happens, so tests and try-outs can act out every case:
- `nofill…`: nothing fills (the market moved past the protection);
- `half…`: half fills, the rest is cancelled;
- `lost…`: the order goes through but the answer is lost (an "unknown" outcome, found again
  with `lookup`);
- anything else: fills in full, at the limit price (or `PRICES` for market orders), 0.6 % fee.
`PLACED` keeps every order by our id, like an exchange's own record.
"""

from decimal import Decimal

from app.orders import Fill, Order, OrderClient, OrderError, Rules, register

PRICES: dict[str, Decimal] = {"BTC": Decimal("60000"), "ETH": Decimal("3000")}
FEE = Decimal("0.006")
PLACED: dict[str, Fill] = {}


class DemoOrders(OrderClient):
    exchange = None

    def rules(self, base: str, quote: str) -> Rules:
        if base.upper() not in PRICES or quote.upper() != "USD":
            raise OrderError(f"The demo exchange has no {base}/{quote} market")
        return Rules(
            symbol=f"{base}-{quote}".upper(),
            base_step=Decimal("0.00000001"),
            base_min=Decimal("0.00001"),
            quote_min=Decimal("1"),
            price_step=Decimal("0.01"),
        )

    def check(self, creds: dict, order: Order) -> str:
        if creds.get("key", "").startswith("view"):
            raise OrderError("The demo exchange says this key can't trade", final=True)
        return "The demo exchange would take it"

    def place(self, creds: dict, order: Order) -> Fill:
        key = creds.get("key", "")
        price = order.limit_price or PRICES[order.base.upper()]
        if order.base_size is not None:
            size = order.base_size
        else:
            size = (order.quote_size / price / (1 + FEE)).quantize(Decimal("0.00000001"))
        if key.startswith("nofill"):
            size = Decimal(0)
        elif key.startswith("half"):
            size = (size / 2).quantize(Decimal("0.00000001"))
        value = size * price
        full = size > 0 and (order.base_size is None or size >= order.base_size)
        status = "filled" if full else "partial" if size > 0 else "unfilled"
        fill = Fill(
            f"demo-{len(PLACED) + 1}",
            order.client_id,
            status,
            size,
            value,
            (value * FEE).quantize(Decimal("0.01")),
            order.quote,
            price if size > 0 else None,
        )
        PLACED[order.client_id] = fill
        if key.startswith("lost"):
            raise OrderError("The demo exchange's answer was lost", unknown=True)
        return fill

    def lookup(self, creds: dict, order: Order) -> Fill | None:
        return PLACED.get(order.client_id)


DEMO_ORDERS = register("demo", DemoOrders())
