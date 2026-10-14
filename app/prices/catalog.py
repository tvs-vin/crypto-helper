"""Which coins and fiat currencies the app can price."""

from dataclasses import dataclass

# symbol -> (CoinGecko id, name). These can't be removed or overwritten.
BUILTIN_COINS: dict[str, tuple[str, str]] = {
    "BTC": ("bitcoin", "Bitcoin"),
    "ETH": ("ethereum", "Ethereum"),
    "SOL": ("solana", "Solana"),
    "ADA": ("cardano", "Cardano"),
    "XRP": ("ripple", "XRP"),
    "DOGE": ("dogecoin", "Dogecoin"),
    "LTC": ("litecoin", "Litecoin"),
    "DOT": ("polkadot", "Polkadot"),
    "AVAX": ("avalanche-2", "Avalanche"),
    "LINK": ("chainlink", "Chainlink"),
    "USDT": ("tether", "Tether"),
    "USDC": ("usd-coin", "USDC"),
    "BNB": ("binancecoin", "BNB"),
    "BCH": ("bitcoin-cash", "Bitcoin Cash"),
    "XLM": ("stellar", "Stellar"),
    "ATOM": ("cosmos", "Cosmos Hub"),
    "TRX": ("tron", "TRON"),
    "SHIB": ("shiba-inu", "Shiba Inu"),
}

# fiat -> digits after the point when showing a value (JPY has no cents).
FIATS: dict[str, int] = {"usd": 2, "eur": 2, "gbp": 2, "jpy": 0, "cad": 2, "aud": 2}
DEFAULT_FIAT = "usd"
MAX_CUSTOM_COINS = 100


@dataclass(frozen=True)
class Coin:
    symbol: str
    coingecko_id: str
    name: str
    builtin: bool


def all_coins(db) -> dict[str, Coin]:
    """Built-in coins plus the custom ones in the database, by symbol."""
    from sqlalchemy import select

    from app.models import CustomCoin

    coins = {s: Coin(s, cid, name, True) for s, (cid, name) in BUILTIN_COINS.items()}
    for c in db.scalars(select(CustomCoin)):
        coins.setdefault(c.symbol, Coin(c.symbol, c.coingecko_id, c.name, False))
    return coins
