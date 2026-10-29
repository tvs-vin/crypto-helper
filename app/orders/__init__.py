"""Placing real orders (phase 4, 13b). One `OrderClient` per exchange, in its own module, with
its own `TRADE_ENDPOINTS`: the only calls it may make with a key. Nothing here can withdraw,
transfer or convert (tests/test_orders.py scans every module for it).

The rules every client follows:
- **Nothing lingers:** every order is immediate-or-cancel. Whatever doesn't fill at once is
  cancelled by the exchange, so a crash never leaves an order on the book. (No cancel calls
  needed, so there are none.)
- **Price protection:** a limit order is at most `protection_pct` worse than the price the bot
  saw. "Market" orders are real market orders where the exchange has them; Gemini doesn't
  (its API has no market orders "because they provide you with no price protection"), so there
  it's an immediate-or-cancel limit order `market_band_pct` away.
- **Our own order id on every order** (`client_id`): if the network fails after sending, the
  outcome is unknown (`OrderError.unknown`) and the caller looks the order up by that id; it
  never just sends it again.
- Sizes are rounded *down* to each market's steps, prices to its price step (never past the
  protection), and orders below the exchange's minimums are refused before anything is sent.

Every call talks to the network: callers never hold a database session meanwhile.
"""

import secrets
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.sync import SourceError


class OrderError(Exception):
    """An order failed. `unknown`: it may or may not have reached the exchange (look it up)."""

    def __init__(self, message: str, *, unknown: bool = False, final: bool = False):
        super().__init__(message)
        self.unknown, self.final = unknown, final


class TooSmall(OrderError):
    pass


@dataclass(frozen=True)
class Rules:
    """A market's limits, from the exchange's public data."""

    symbol: str  # the exchange's name for the market (BTC-USD, XBTUSD, btcusd, BTCUSD)
    base_step: Decimal  # sizes are a multiple of this
    base_min: Decimal
    quote_min: Decimal  # the smallest order value
    price_step: Decimal
    quote_step: Decimal = Decimal("0.01")
    market_orders: bool = True  # False: Gemini (immediate-or-cancel limit orders instead)
    market_buy_by_quote: bool = True  # market buys are sized in money (quote), not coins


@dataclass
class Order:
    client_id: str
    base: str
    quote: str
    side: str  # "buy" | "sell"
    kind: str  # "limit" | "market"
    base_size: Decimal | None = None
    quote_size: Decimal | None = None  # market buys by value
    limit_price: Decimal | None = None
    symbol: str = ""  # the exchange's market name (from Rules)


@dataclass
class Fill:
    """What happened to an order. `base`: coins bought or sold; `value`: their price in the
    quote currency before the fee."""

    order_id: str | None
    client_id: str
    status: str  # "filled" | "partial" | "unfilled"
    base: Decimal
    value: Decimal
    fee: Decimal
    fee_asset: str
    avg_price: Decimal | None = None


def transient(e: Exception) -> bool:
    """A failure of the network or the exchange's servers (try again later), not an answer."""
    text = str(e)
    return text.startswith("Couldn't reach") or "answered 5" in text or "slow down" in text


def new_client_id() -> str:
    return "ch-" + secrets.token_hex(12)  # letters, digits and '-': every exchange accepts it


def floor_to(x: Decimal, step: Decimal) -> Decimal:
    return (x / step).to_integral_value(rounding=ROUND_FLOOR) * step if step > 0 else x


def ceil_to(x: Decimal, step: Decimal) -> Decimal:
    return (x / step).to_integral_value(rounding=ROUND_CEILING) * step if step > 0 else x


def num(d: Decimal) -> str:
    """A plain decimal for an exchange: no exponent, no trailing zeros."""
    text = format(d, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def prepare(
    rules: Rules,
    *,
    base: str,
    quote: str,
    side: str,
    kind: str,
    price: Decimal,
    spend: Decimal | None = None,
    units: Decimal | None = None,
    protection_pct: Decimal = Decimal("1"),
    market_band_pct: Decimal = Decimal("5"),
    client_id: str | None = None,
) -> Order:
    """The order to send: buys by `spend` (money, the most the order may cost before fees),
    sells by `units`. Refuses (TooSmall) what the exchange would refuse for its size."""
    if side not in ("buy", "sell") or kind not in ("limit", "market"):
        raise ValueError("side is buy or sell; kind is limit or market")
    if price <= 0:
        raise OrderError("No price to protect the order with")
    if side == "buy" and (spend is None or spend <= 0):
        raise TooSmall("Nothing to spend")
    if side == "sell" and (units is None or units <= 0):
        raise TooSmall("Nothing to sell")
    order = Order(client_id or new_client_id(), base, quote, side, kind, symbol=rules.symbol)
    band = (protection_pct if kind == "limit" else market_band_pct) / 100
    if kind == "limit" or not rules.market_orders:
        order.kind = "limit"
        if side == "buy":  # never pay more than price + protection
            order.limit_price = floor_to(price * (1 + band), rules.price_step)
            order.base_size = floor_to(spend / order.limit_price, rules.base_step)
        else:  # never sell for less than price - protection
            order.limit_price = ceil_to(price * (1 - band), rules.price_step)
            order.base_size = floor_to(units, rules.base_step)
        value = order.base_size * order.limit_price
    elif side == "buy" and rules.market_buy_by_quote:
        order.quote_size = floor_to(spend, rules.quote_step)
        value = order.quote_size
    elif side == "buy":  # sized in coins: leave room for the price to move by the band
        order.base_size = floor_to(spend / (price * (1 + band)), rules.base_step)
        value = order.base_size * price
    else:
        order.base_size = floor_to(units, rules.base_step)
        value = order.base_size * price
    if order.base_size is not None and order.base_size < max(rules.base_min, rules.base_step):
        raise TooSmall(
            f"Below {base}'s smallest order on this exchange ({num(rules.base_min)} {base})"
        )
    if value < rules.quote_min:
        raise TooSmall(f"Below the smallest order value ({num(rules.quote_min)} {quote})")
    return order


class OrderClient:
    """One exchange's order calls. Subclasses set `exchange` (the app/sync client, for its
    signing and base address) and implement these."""

    exchange = None
    # Whether the exchange can check an order without trading (preview / validate / test).
    can_check = True

    def rules(self, base: str, quote: str) -> Rules:  # pragma: no cover
        raise NotImplementedError

    def check(self, creds: dict, order: Order) -> str:  # pragma: no cover
        """Ask the exchange whether it would take this order, without trading."""
        raise NotImplementedError

    def place(self, creds: dict, order: Order) -> Fill:  # pragma: no cover
        raise NotImplementedError

    def lookup(self, creds: dict, order: Order) -> Fill | None:  # pragma: no cover
        """After an unknown outcome: the order by our id, or None if it never arrived."""
        raise NotImplementedError

    def _send(self, fn):
        """Run the call that places an order: a network failure means "unknown", never "no"."""
        try:
            return fn()
        except SourceError as e:
            text = str(e)
            if transient(e):
                raise OrderError(
                    f"{text}: the order may or may not have gone through", unknown=True
                ) from None
            raise OrderError(text, final=e.final) from None


CLIENTS: dict[str, OrderClient] = {}


def register(exchange_id: str, client: OrderClient) -> OrderClient:
    CLIENTS[exchange_id] = client
    return client


def client_for(exchange_id: str) -> OrderClient | None:
    from app.orders import binanceus, coinbase, demo, gemini, kraken  # noqa: F401  (register)

    return CLIENTS.get(exchange_id)
