"""Refuse text that looks like a recovery phrase or private key.

Whoever has a wallet's seed phrase or private key owns its coins, and this app must never
store one (project rule). Beginners paste them into the wrong box, so every free-text wallet
field is checked. The text that tripped the guard is never logged or echoed back.
"""

import re
from functools import cache
from importlib import resources

_B58 = "1-9A-HJ-NP-Za-km-z"
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 32-byte private key as hex (Ethereum and most EVM wallets export this).
    (re.compile(r"(?<![0-9a-fA-F])(0x)?[0-9a-fA-F]{64}(?![0-9a-fA-F])"), "a private key"),
    # Bitcoin WIF private keys (mainnet 5/K/L, testnet 9/c).
    (
        re.compile(
            rf"(?<![{_B58}])(5[HJK][{_B58}]{{49}}|[KLc][{_B58}]{{51}}|9[{_B58}]{{50}})"
            rf"(?![{_B58}])"
        ),
        "a Bitcoin private key",
    ),
    # BIP32 extended private keys.
    (re.compile(rf"\b[xyztuv]prv[{_B58}]{{100,}}"), "an extended private key"),
    # Solana secret key: 64 bytes in base58 (87-88 chars) ...
    (re.compile(rf"(?<![{_B58}])[{_B58}]{{86,90}}(?![{_B58}])"), "a Solana private key"),
    # ... or the JSON array keypair file.
    (re.compile(r"\[\s*(\d{1,3}\s*,\s*){63}\d{1,3}\s*\]"), "a Solana keypair file"),
]
# A transaction hash is also 64 hex characters; allow it inside an explorer link.
_TX_LINK = re.compile(r"/tx/(0x)?[0-9a-fA-F]{64}")
SEED_MIN_WORDS = 12


@cache
def bip39_words() -> frozenset[str]:
    text = resources.files("app").joinpath("data/bip39_english.txt").read_text()
    words = frozenset(text.split())
    assert len(words) == 2048, "BIP39 word list is damaged"
    return words


def _longest_bip39_run(text: str) -> int:
    words = bip39_words()
    best = run = 0
    for token in re.findall(r"[A-Za-z]+", text):
        run = run + 1 if token.lower() in words else 0
        best = max(best, run)
    return best


def find_secret(text: str | None) -> str | None:
    """Return a plain warning if `text` looks like a seed phrase or private key."""
    if not text:
        return None
    if _longest_bip39_run(text) >= SEED_MIN_WORDS:
        kind = "a recovery (seed) phrase"
    else:
        scrubbed = _TX_LINK.sub("", text)
        kind = next((label for pattern, label in _PATTERNS if pattern.search(scrubbed)), None)
        if kind is None:
            return None
    return (
        f"That looks like {kind}. Never type it into any app or website: whoever has it "
        "can take every coin in that wallet, and this app must never store one. If it was "
        "real and you shared it anywhere, move the funds to a new wallet. For a wallet here "
        "you only need its public address (from the wallet's Receive screen)."
    )
