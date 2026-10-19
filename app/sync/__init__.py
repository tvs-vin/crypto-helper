"""Syncing wallets from outside sources (phase 2): exchange accounts through read-only API keys
(11b) and public addresses on a blockchain (11c).

Each exchange is an `Exchange` in `EXCHANGES`: the credential fields it needs, how to check that
a key is read-only, and how to read balances. A client only contains the calls it needs to
read: there's nothing in this package that could place an order or move funds.

Everything here talks to the network: callers never hold a database session meanwhile.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class SourceError(Exception):
    """Reading a source failed. The message is safe to show and store (never a secret).
    `final`: retrying won't help until someone acts (a revoked or refused key)."""

    def __init__(self, message: str, *, final: bool = False):
        super().__init__(message)
        self.final = final


@dataclass
class Field:
    name: str
    label: str
    secret: bool = True  # shown as a password box; never sent back
    help: str = ""
    multiline: bool = False


@dataclass
class Check:
    """What a key is allowed to do. `read_only`: True (checked), False (can trade or move
    funds: refused) or None (the exchange can't tell us: the owner has to confirm)."""

    read_only: bool | None
    summary: str


@dataclass
class Fetched:
    """Balances as the source reports them, by its own asset code, as exact text."""

    balances: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class TradeRow:
    """One trade as the trade log keeps it: `side` is buy or sell of `base`; `total` is in
    `quote`, before the fee; `time` is UTC (naive)."""

    trade_id: str
    order_id: str | None
    time: datetime
    base: str
    quote: str
    side: str
    amount: Decimal
    price: Decimal
    total: Decimal
    fee: Decimal
    fee_asset: str


@dataclass
class Exchange:
    id: str
    name: str
    fields: list[Field]
    guide: str  # the Help page with the step-by-step guide
    # How to confirm a key is read-only when the exchange can't report it.
    confirm_text: str = ""
    # Exchange asset code -> our symbol, for codes that differ (Kraken's XXBT is BTC).
    aliases: dict[str, str] = field(default_factory=dict)

    def check(self, creds: dict) -> Check:  # pragma: no cover - each exchange overrides
        raise NotImplementedError

    def fetch(self, creds: dict) -> Fetched:  # pragma: no cover
        raise NotImplementedError

    # What to tick on the exchange for trade history, shown when it's missing.
    trades_permission: str = ""

    def trades(self, creds: dict, state: dict, assets: set[str]):  # pragma: no cover
        """New trades since `state` (where the last import stopped), and the state to keep.
        `assets`: coin codes worth asking about, for exchanges that list trades per market."""
        raise NotImplementedError

    def mask(self, creds: dict) -> str:
        """Enough of the key to recognise it, nothing usable."""
        key = str(creds.get(self.fields[0].name, ""))
        return f"{self.name} key …{key[-4:]}" if len(key) >= 8 else f"{self.name} key"


EXCHANGES: dict[str, Exchange] = {}


def register(exchange: Exchange) -> Exchange:
    EXCHANGES[exchange.id] = exchange
    return exchange


def available(settings) -> dict[str, Exchange]:
    """The exchanges this install offers (the demo one only when switched on for testing)."""
    from app.sync import binanceus, coinbase, demo, gemini, kraken  # noqa: F401  (they register)

    shown = [e for k, e in EXCHANGES.items() if k != "demo" or settings.sync_demo]
    return {e.id: e for e in sorted(shown, key=lambda e: (e.id == "demo", e.name.lower()))}
