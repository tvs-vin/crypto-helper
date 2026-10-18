"""A pretend exchange, for tests and trying the sync screens out (BOT_SYNC_DEMO=true only).

It never touches the network. The key decides what happens:
- starts with `trade`: the key "can trade" (refused);
- starts with `unknown`: the exchange "can't say" (needs the owner's confirmation);
- starts with `fail`: reading fails (and `failfinal`: as if the key was revoked);
- anything else: read-only, holding 0.5 BTC, 2.25 ETH, 100 USDC and 7 of an unknown "ZZZ".
`demo.BALANCES` can be changed by tests.
"""

from decimal import Decimal

from app.sync import Check, Exchange, Fetched, Field, SourceError, register

BALANCES = {"XBT": "0.5", "ETH": "2.25", "USDC": "100", "ZZZ": "7"}


class Demo(Exchange):
    def check(self, creds: dict) -> Check:
        key = creds.get("key", "")
        if key.startswith("trade"):
            return Check(False, "This key can trade")
        if key.startswith("unknown"):
            return Check(None, "The demo exchange can't say what this key may do")
        return Check(True, "View only")

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
        aliases={"XBT": "BTC"},
    )
)

__all__ = ["DEMO", "BALANCES", "SourceError"]
