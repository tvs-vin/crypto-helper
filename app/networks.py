"""Blockchain networks: which exist, which coins live on which, and address formats.

Sending a coin to a different network than the one it's on usually loses it, so the app
uses this to refuse simulated transfers that would be impossible (or ruinous) for real.
"""

import re
from dataclasses import dataclass

# slug -> display name. Users can also type networks that aren't listed here.
KNOWN_NETWORKS: dict[str, str] = {
    "bitcoin": "Bitcoin",
    "ethereum": "Ethereum",
    "solana": "Solana",
    "base": "Base",
    "arbitrum": "Arbitrum One",
    "optimism": "OP Mainnet (Optimism)",
    "polygon": "Polygon PoS",
    "bsc": "BNB Smart Chain",
    "avalanche": "Avalanche C-Chain",
    "tron": "Tron",
    "cardano": "Cardano",
    "xrp": "XRP Ledger",
    "dogecoin": "Dogecoin",
    "litecoin": "Litecoin",
    "polkadot": "Polkadot",
    "cosmos": "Cosmos Hub",
    "stellar": "Stellar",
    "bitcoin-cash": "Bitcoin Cash",
}

# Where each well-known coin natively or officially exists. A wrapped/bridged copy on
# another chain is a *different token* (BTC on Ethereum is WBTC), so it isn't listed.
COIN_NETWORKS: dict[str, frozenset[str]] = {
    "BTC": frozenset({"bitcoin"}),
    "ETH": frozenset({"ethereum", "arbitrum", "optimism", "base"}),
    "SOL": frozenset({"solana"}),
    "ADA": frozenset({"cardano"}),
    "XRP": frozenset({"xrp"}),
    "DOGE": frozenset({"dogecoin"}),
    "LTC": frozenset({"litecoin"}),
    "DOT": frozenset({"polkadot"}),
    "AVAX": frozenset({"avalanche"}),
    "LINK": frozenset({"ethereum", "arbitrum", "optimism", "base", "polygon", "bsc", "avalanche"}),
    "USDT": frozenset(
        {"ethereum", "tron", "solana", "bsc", "polygon", "arbitrum", "avalanche", "optimism"}
    ),
    "USDC": frozenset(
        {"ethereum", "solana", "base", "polygon", "arbitrum", "optimism", "avalanche", "stellar"}
    ),
    "BNB": frozenset({"bsc"}),
    "BCH": frozenset({"bitcoin-cash"}),
    "XLM": frozenset({"stellar"}),
    "ATOM": frozenset({"cosmos"}),
    "TRX": frozenset({"tron"}),
    "SHIB": frozenset({"ethereum"}),
}

NETWORK_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")

_B58 = "1-9A-HJ-NP-Za-km-z"
_EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
ADDRESS_FORMATS: dict[str, tuple[re.Pattern, str]] = {
    "bitcoin": (
        re.compile(rf"^(bc1[ac-hj-np-z02-9]{{11,71}}|[13][{_B58}]{{25,34}})$"),
        "bc1…, 1… or 3…",
    ),
    "solana": (re.compile(rf"^[{_B58}]{{32,44}}$"), "32-44 base58 characters"),
    "tron": (re.compile(rf"^T[{_B58}]{{33}}$"), "T followed by 33 characters"),
    "cardano": (re.compile(r"^addr1[a-z0-9]{50,}$"), "addr1…"),
    "xrp": (re.compile(rf"^r[{_B58}]{{24,34}}$"), "r…"),
    "dogecoin": (re.compile(rf"^D[{_B58}]{{33}}$"), "D…"),
    "litecoin": (
        re.compile(rf"^(ltc1[ac-hj-np-z02-9]{{11,71}}|[LM3][{_B58}]{{26,33}})$"),
        "ltc1…, L…, M… or 3…",
    ),
    "polkadot": (re.compile(rf"^1[{_B58}]{{45,47}}$"), "1… (47-48 characters)"),
    "cosmos": (re.compile(r"^cosmos1[ac-hj-np-z02-9]{38}$"), "cosmos1…"),
    "stellar": (re.compile(r"^G[A-Z2-7]{55}$"), "G followed by 55 characters"),
    "bitcoin-cash": (re.compile(r"^(bitcoincash:)?[qp][ac-hj-np-z02-9]{41}$"), "q… or p…"),
}
for _evm in ("ethereum", "base", "arbitrum", "optimism", "polygon", "bsc", "avalanche"):
    ADDRESS_FORMATS[_evm] = (_EVM, "0x followed by 40 hex characters")
_GENERIC_ADDRESS = re.compile(r"^[A-Za-z0-9:._-]{10,128}$")


class NetworkError(ValueError):
    pass


def normalize_network(value: str) -> str:
    slug = value.strip().lower().replace(" ", "-")
    if not NETWORK_RE.match(slug):
        raise NetworkError("Networks are 2-32 characters: letters, digits and dashes.")
    return slug


def network_name(slug: str | None) -> str:
    return KNOWN_NETWORKS.get(slug, slug) if slug else "no network"


def check_address(address: str, network: str | None) -> None:
    fmt = ADDRESS_FORMATS.get(network or "")
    if fmt:
        pattern, shape = fmt
        if not pattern.match(address):
            raise NetworkError(
                f"That doesn't look like a {network_name(network)} address (expected {shape}). "
                "Copy it again from your wallet's Receive screen."
            )
    elif not _GENERIC_ADDRESS.match(address):
        raise NetworkError("Addresses are 10-128 characters without spaces.")


def coin_allowed_on(symbol: str, network: str | None) -> str | None:
    """None if the coin can live on that network, else a plain explanation."""
    if network is None:
        return None
    allowed = COIN_NETWORKS.get(symbol)
    if allowed is None or network in allowed:
        return None
    where = ", ".join(network_name(n) for n in sorted(allowed))
    return (
        f"{symbol} doesn't exist on {network_name(network)}; it lives on {where}. A {symbol} "
        f"look-alike on {network_name(network)} would be a different, wrapped token with its own "
        "symbol (for example BTC on Ethereum is WBTC)."
    )


# ---- reading balances on-chain (phase 2, milestone 11c) ------------------------------------
# Every contract below was checked on 2026-10-18 on the chain itself (symbol and decimals) and
# against the issuer's own list (Circle for USDC, Tether's USDT0 deployments). Only these are
# read: tokens sent to an address that aren't listed (airdropped scam tokens are common) are
# ignored. Mirrored in WIKI/reference/networks.md.


@dataclass(frozen=True)
class Token:
    symbol: str
    contract: str
    decimals: int


# The coin each EVM network pays fees in, and its decimals. POL isn't a built-in coin: it shows
# as "not tracked" until someone adds it (Settings → Prices).
NATIVE: dict[str, tuple[str, int]] = {
    "ethereum": ("ETH", 18),
    "base": ("ETH", 18),
    "arbitrum": ("ETH", 18),
    "optimism": ("ETH", 18),
    "polygon": ("POL", 18),
}

TOKENS: dict[str, tuple[Token, ...]] = {
    "ethereum": (
        Token("USDC", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
        Token("USDT", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
        Token("LINK", "0x514910771AF9Ca656af840dff83E8264EcF986CA", 18),
        Token("SHIB", "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE", 18),
    ),
    "base": (Token("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),),
    "arbitrum": (
        Token("USDC", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),
        Token("USDT", "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6),  # USD₮0
    ),
    "optimism": (
        Token("USDC", "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6),
        Token("USDT", "0x01bFF41798a0BcF287b996046Ca68b395DbC1071", 6),  # USD₮0
        Token("USDT", "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58", 6),  # older bridged USDT
    ),
    "polygon": (
        Token("USDC", "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6),
        Token("USDT", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6),  # USDT0
    ),
}

# Networks whose balances can be synced from public addresses (Bitcoin also from an xpub).
SYNCABLE = frozenset({"bitcoin", *NATIVE})
