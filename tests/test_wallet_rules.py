"""Pure rules: money, networks, colors, the seed/private-key guard."""

from decimal import Decimal

import pytest

from app import colors, money, networks
from app.secret_guard import bip39_words, find_secret

SEED12 = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)
SEED24 = " ".join(
    [
        "legal",
        "winner",
        "thank",
        "year",
        "wave",
        "sausage",
        "worth",
        "useful",
        "legal",
        "winner",
        "thank",
        "yellow",
    ]
    * 2
)


# ---- money -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0", "0"),
        ("1", "1"),
        ("1.50", "1.5"),
        ("0.000000000000000001", "0.000000000000000001"),
        ("999999999999999999", "999999999999999999"),
        (" 2.0 ", "2"),
    ],
)
def test_parse_and_format(text, expected):
    assert money.format_amount(money.parse_amount(text)) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "-1",
        "1e5",
        "NaN",
        "Infinity",
        "1,000",
        "0.0000000000000000001",
        "1000000000000000000",
        "",
        ".5",
        "5.",
        "0x10",
        "1 000",
    ],
)
def test_rejects_malformed_amounts(bad):
    with pytest.raises(money.AmountError):
        money.parse_amount(bad)


@pytest.mark.parametrize("number", [0.1, 1, 2.5, True, None])
def test_json_numbers_are_refused_with_a_reason(number):
    with pytest.raises(money.AmountError, match="as text"):
        money.parse_amount(number)


def test_exact_arithmetic():
    assert money.add(Decimal("0.1"), Decimal("0.2")) == Decimal("0.3")
    tiny = Decimal("0.000000000000000001")
    assert money.subtract(Decimal("1"), tiny) == Decimal("0.999999999999999999")
    with pytest.raises(money.AmountError, match="too large"):
        money.add(Decimal("999999999999999999"), Decimal("1"))


def test_zero_can_be_disallowed():
    with pytest.raises(money.AmountError, match="more than zero"):
        money.parse_amount("0", allow_zero=False)


# ---- networks ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "network,address",
    [
        ("ethereum", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"),
        ("base", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"),
        ("bitcoin", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"),
        ("bitcoin", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"),
        ("bitcoin", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"),
        ("solana", "7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZV3qyouov87awMs"),
        ("tron", "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"),
        ("stellar", "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ"),
        ("my-testnet", "custom-address-123"),
    ],
)
def test_valid_addresses(network, address):
    networks.check_address(address, network)


@pytest.mark.parametrize(
    "network,address",
    [
        ("ethereum", "0x742d35Cc6634C0532925a3b844Bc454e4438f44"),  # one short
        ("ethereum", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"),  # bitcoin addr on ethereum
        ("bitcoin", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"),
        ("solana", "0OIl0OIl0OIl0OIl0OIl0OIl0OIl0OIl"),  # not base58
        ("my-testnet", "has spaces in it"),
    ],
)
def test_invalid_addresses(network, address):
    with pytest.raises(networks.NetworkError):
        networks.check_address(address, network)


def test_coin_network_table():
    assert networks.coin_allowed_on("BTC", "bitcoin") is None
    assert "WBTC" in networks.coin_allowed_on("BTC", "ethereum")
    assert networks.coin_allowed_on("USDC", "solana") is None
    assert networks.coin_allowed_on("USDC", "bitcoin") is not None
    assert networks.coin_allowed_on("PEPE", "anything") is None  # unknown coins are allowed
    assert networks.coin_allowed_on("BTC", None) is None  # no network: exchange books


def test_every_known_coin_points_at_known_networks():
    for symbol, nets in networks.COIN_NETWORKS.items():
        assert nets <= set(networks.KNOWN_NETWORKS), symbol


@pytest.mark.parametrize("raw,slug", [("Ethereum", "ethereum"), (" BNB chain ", "bnb-chain")])
def test_network_normalisation(raw, slug):
    assert networks.normalize_network(raw) == slug


# ---- colors ------------------------------------------------------------------------------


def test_default_primary_is_stable_and_distinct():
    assert colors.default_primary("Coinbase") == colors.default_primary("Coinbase")
    assert colors.default_primary("Coinbase") != colors.default_primary("Ledger")
    assert colors.HEX_RE.match(colors.default_primary("x"))


@pytest.mark.parametrize("scheme", colors.SCHEMES)
def test_every_scheme_gives_a_different_valid_color(scheme):
    second = colors.derive_secondary("#3b82f6", scheme)
    assert colors.HEX_RE.match(second) and second != "#3b82f6"


def test_complementary_is_opposite():
    assert colors.derive_secondary("#ff0000", "complementary") == "#00ffff"


def test_resolve_custom_vs_auto():
    auto = colors.resolve("w", "#3b82f6", "#000000", "auto", "triadic")
    assert auto["secondary"] == colors.derive_secondary("#3b82f6", "triadic")
    custom = colors.resolve("w", "#3b82f6", "#000000", "custom", "triadic")
    assert custom["secondary"] == "#000000"
    assert colors.resolve("w", None, None, "auto", "analogous")["primary_is_default"] is True


@pytest.mark.parametrize("bad", ["red", "#fff", "#12345g", "3b82f6"])
def test_bad_hex(bad):
    with pytest.raises(ValueError):
        colors.normalize_hex(bad)


# ---- seed phrase / private key guard -----------------------------------------------------


def test_official_wordlist_loaded():
    words = bip39_words()
    assert len(words) == 2048 and "abandon" in words and "zoo" in words


@pytest.mark.parametrize(
    "text",
    [
        SEED12,
        SEED24,
        SEED12.upper(),
        "my seed: " + SEED12 + " (keep safe!)",
        SEED12.replace(" ", "\n"),
        SEED12.replace(" ", ", "),
        "4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318",
        "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318",
        "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ",
        "KwDiBf89QgGbjEhKnhXJuH7LrciVrZi3qYjgd9M7rFU73sVHnoWn",
        "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3"
        "TGtRBeJgk33yuGBxrMPHi",
        "[" + ",".join(["12"] * 64) + "]",
    ],
)
def test_secrets_are_caught(text):
    assert find_secret(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Cold storage. Bought 2021 on Coinbase, Ledger is in the drawer.",
        " ".join(SEED12.split()[:11]),  # 11 words: not a phrase
        "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",  # an address
        "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
        "7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZV3qyouov87awMs",
        "See https://etherscan.io/tx/0x" + "ab" * 32,  # tx hash inside an explorer link
        "I always buy a little every month and never sell during a crash",
    ],
)
def test_normal_text_passes(text):
    assert find_secret(text) is None


def test_warning_explains_without_repeating_the_secret():
    msg = find_secret(SEED12)
    assert "abandon" not in msg and "recovery" in msg and "public address" in msg
