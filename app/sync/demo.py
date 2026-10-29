"""A pretend exchange, for tests and trying the sync screens out (BOT_SYNC_DEMO=true only).

It never touches the network. The key decides what happens:
- starts with `trade`: the key "can trade" (refused);
- starts with `unknown`: the exchange "can't say" (needs the owner's confirmation);
- starts with `fail`: reading fails (and `failfinal`: as if the key was revoked);
- anything else: read-only, holding 0.5 BTC, 2.25 ETH, 100 USDC and 7 of an unknown "ZZZ".
`demo.BALANCES` can be changed by tests.
"""

from decimal import Decimal

from app.sync import Check, Exchange, Fetched, Field, SourceError, TradeCheck, TradeRow, register
from app.sync.http import parse_time

BALANCES = {"XBT": "0.5", "ETH": "2.25", "USDC": "100", "ZZZ": "7"}
# (id, ISO time, base, quote, side, amount, price, fee)
TRADES = [
    ("d1", "2026-01-05T10:00:00Z", "XBT", "USD", "buy", "0.5", "40000", "20"),
    ("d2", "2026-02-10T15:30:00Z", "ETH", "USD", "buy", "3", "2000", "6"),
    ("d3", "2026-03-15T09:45:00Z", "ETH", "USD", "sell", "0.75", "2500", "1.875"),
]


class Demo(Exchange):
    def check(self, creds: dict) -> Check:
        key = creds.get("key", "")
        if key.startswith("trade"):
            return Check(False, "This key can trade")
        if key.startswith("unknown"):
            return Check(None, "The demo exchange can't say what this key may do")
        return Check(True, "View only")

    def check_trading(self, creds: dict) -> TradeCheck:
        """Trading keys: `withdraw…` can withdraw (refused), `view…` can't trade (refused),
        `unknown…` can't say (needs confirming), `iplocked…` is address-locked; else fine."""
        key = creds.get("key", "")
        if key.startswith("withdraw"):
            return TradeCheck(True, True, False, "The demo exchange says this key can withdraw")
        if key.startswith("view"):
            return TradeCheck(False, False, False, "The demo exchange says this key can't trade")
        if key.startswith("unknown"):
            return TradeCheck(None, None, None, "The demo exchange can't say")
        if key.startswith("fail"):
            raise SourceError("The demo exchange didn't answer")
        return TradeCheck(True, False, key.startswith("iplocked"), "checked with the demo exchange")

    def trades(self, creds: dict, state: dict, assets: set[str]):
        if creds.get("key", "").startswith("notrades"):
            raise SourceError("The demo exchange says this key can't read trades", final=True)
        seen = int(state.get("seen", 0))
        rows = [
            TradeRow(
                tid,
                None,
                parse_time(when),
                self.aliases.get(b, b),
                q,
                side,
                Decimal(a),
                Decimal(p),
                Decimal(a) * Decimal(p),
                Decimal(f),
                q,
            )
            for tid, when, b, q, side, a, p, f in TRADES[seen:]
        ]
        return rows, {"seen": len(TRADES)}

    def fetch(self, creds: dict) -> Fetched:
        key = creds.get("key", "")
        if key.startswith("failfinal"):
            raise SourceError("The demo exchange says this key was deleted", final=True)
        if key.startswith("fail"):
            raise SourceError("The demo exchange didn't answer")
        return Fetched({k: Decimal(v) for k, v in BALANCES.items()})


DEMO = register(
    Demo(
        id="demo",
        name="Demo exchange",
        fields=[
            Field("key", "API key", secret=False),
            Field("secret", "API secret", help="Anything: the demo exchange is pretend."),
        ],
        guide="guides/exchange-connections",
        confirm_text="I created this key with view permission only.",
        trading_confirm_text="I created this key without withdrawal or transfer permission.",
        trades_permission="(any key works on the demo exchange)",
        aliases={"XBT": "BTC"},
    )
)

__all__ = ["DEMO", "BALANCES", "SourceError"]
