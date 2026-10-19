"""Wallets, holdings and simulated transfers: the rules, independent of HTTP.

Callers own the transaction: they call begin_immediate() before anything that checks a
balance and then changes it, write the audit entry, and commit.
"""

import re
import unicodedata
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import colors, money, networks
from app.models import Holding, Transfer, User, Wallet, WalletSource
from app.secret_guard import find_secret

KINDS = ("exchange", "onchain", "paper")
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,10}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9 -]{0,23}$")
MAX_TAGS = 20
SIMULATED_LABEL = "Simulated, no real funds move"
EXCHANGE_REMINDER = (
    "For a real transfer involving an exchange, choose the matching network on the "
    "exchange's deposit or withdrawal page; the wrong one can lose the coins."
)


class WalletError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


# ---- validation --------------------------------------------------------------------------


def guard(**fields: str | list[str] | None) -> None:
    """Refuse any field that looks like a seed phrase or private key (never echoed).

    Lists (tags) are checked item by item: joining them would turn twelve ordinary tags
    that happen to be BIP39 words ("family", "travel", ...) into a false "seed phrase".
    """
    for name, value in fields.items():
        for item in value if isinstance(value, list) else [value]:
            warning = find_secret(item)
            if warning:
                raise WalletError(422, warning, field=name)


def clean_text(value: str | None, field: str, max_len: int, *, required=False) -> str | None:
    if value is None:
        if required:
            raise WalletError(422, f"{field} is required.")
        return None
    value = unicodedata.normalize("NFC", value).strip()
    if any(unicodedata.category(c) == "Cc" for c in value):
        raise WalletError(422, f"{field} can't contain control characters.")
    if not value:
        if required:
            raise WalletError(422, f"{field} can't be empty.")
        return None
    if len(value) > max_len:
        raise WalletError(422, f"{field} is at most {max_len} characters.")
    return value


def clean_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise WalletError(422, "Coin symbols are 2-10 letters or digits, like BTC or USDC.")
    return symbol


def clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for raw in tags:
        tag = " ".join(raw.strip().lower().split())
        if ":" in tag:
            raise WalletError(
                422,
                f"Tag {tag!r}: tags with ':' are built-in and set "
                "automatically (like kind:onchain).",
            )
        if not TAG_RE.match(tag):
            raise WalletError(
                422, f"Tag {tag!r}: tags are 1-24 characters of letters, digits, spaces and dashes."
            )
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise WalletError(422, f"A wallet can have at most {MAX_TAGS} tags.")
    return out


def check_kind_network(kind: str, network: str | None) -> str | None:
    if kind not in KINDS:
        raise WalletError(422, f"kind must be one of {', '.join(KINDS)}.")
    if network is not None:
        try:
            network = networks.normalize_network(network)
        except networks.NetworkError as e:
            raise WalletError(422, str(e)) from None
    if kind == "exchange" and network:
        raise WalletError(
            422,
            "Exchange wallets have no network: the exchange holds the coins "
            "and you pick a network only when you deposit or withdraw.",
        )
    if kind == "onchain" and not network:
        raise WalletError(
            422,
            "On-chain wallets need a network (e.g. ethereum, bitcoin, "
            "solana): it decides which coins it can hold and receive.",
        )
    return network


def check_address(address: str | None, network: str | None) -> None:
    if address:
        try:
            networks.check_address(address, network)
        except networks.NetworkError as e:
            raise WalletError(422, str(e)) from None


def unique_name(db: DbSession, name: str, exclude_id: int | None = None) -> None:
    stmt = select(Wallet.id).where(func.lower(Wallet.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Wallet.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise WalletError(409, f"A wallet named {name!r} already exists.")


# ---- reading -----------------------------------------------------------------------------


def holdings_of(db: DbSession, wallet: Wallet) -> list[Holding]:
    return list(
        db.scalars(select(Holding).where(Holding.wallet_id == wallet.id).order_by(Holding.symbol))
    )


def balance(db: DbSession, wallet: Wallet, symbol: str) -> tuple[Holding | None, Decimal]:
    h = db.scalar(select(Holding).where(Holding.wallet_id == wallet.id, Holding.symbol == symbol))
    return h, (Decimal(h.amount) if h else Decimal(0))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32]


def system_tags(wallet: Wallet, holdings: list[Holding]) -> list[str]:
    """Built-in, read-only tags derived from the wallet itself."""
    tags = [f"kind:{wallet.kind}"]
    if wallet.network:
        tags.append(f"network:{wallet.network}")
    if wallet.provider and _slug(wallet.provider):
        tags.append(f"provider:{_slug(wallet.provider)}")
    tags += [f"coin:{h.symbol.lower()}" for h in holdings]
    if wallet.address:
        tags.append("address:yes")
    if wallet.archived:
        tags.append("status:archived")
    if not holdings:
        tags.append("status:empty")
    return tags


def serialize(wallet: Wallet, holdings: list[Holding]) -> dict:
    return {
        "id": wallet.id,
        "name": wallet.name,
        "nickname": wallet.nickname,
        "display_name": wallet.nickname or wallet.name,
        "kind": wallet.kind,
        "provider": wallet.provider,
        "network": wallet.network,
        "network_name": networks.network_name(wallet.network) if wallet.network else None,
        "address": wallet.address,
        "notes": wallet.notes,
        "colors": colors.resolve(
            wallet.name,
            wallet.color_primary,
            wallet.color_secondary,
            wallet.color_secondary_mode,
            wallet.color_scheme,
        ),
        "tags": list(wallet.tags or []),
        "system_tags": system_tags(wallet, holdings),
        "archived": wallet.archived,
        "holdings": [{"symbol": h.symbol, "amount": h.amount} for h in holdings],
        "created_at": wallet.created_at,
        "updated_at": wallet.updated_at,
    }


# ---- holdings ----------------------------------------------------------------------------


def is_synced(db: DbSession, wallet: Wallet) -> bool:
    """True when the wallet's balances come from an exchange or addresses (phase 2)."""
    return db.get(WalletSource, wallet.id) is not None


def require_manual(db: DbSession, wallet: Wallet, action: str) -> None:
    """A synced wallet's balances mirror the real account: only syncing changes them."""
    if is_synced(db, wallet):
        raise WalletError(
            409,
            f"Can't {action}: {wallet.name} is synced, so its balances mirror the real account "
            "and only syncing changes them. Switch it to manual first if you want to type "
            "balances in.",
        )


def require_active(wallet: Wallet, action: str) -> None:
    if wallet.archived:
        raise WalletError(
            409, f"{wallet.name} is archived, so you can't {action}. Unarchive it first."
        )


def check_coin_on_wallet(wallet: Wallet, symbol: str) -> None:
    problem = networks.coin_allowed_on(symbol, wallet.network)
    if problem:
        raise WalletError(
            409, f"{wallet.name} is on {networks.network_name(wallet.network)}. " + problem
        )


def set_holding(db: DbSession, wallet: Wallet, symbol: str, amount: Decimal) -> tuple[str, str]:
    """Set an exact balance. Returns (old, new) as text. 0 removes the holding."""
    require_active(wallet, "change its balances")
    if amount > 0:
        check_coin_on_wallet(wallet, symbol)
    holding, old = balance(db, wallet, symbol)
    new = money.format_amount(amount)
    if amount == 0:
        if holding is not None:
            db.delete(holding)
    elif holding is None:
        db.add(Holding(wallet_id=wallet.id, symbol=symbol, amount=new))
    else:
        holding.amount = new
    return money.format_amount(old), new


def summary(db: DbSession, include_archived: bool) -> list[dict]:
    stmt = select(Holding, Wallet).join(Wallet, Holding.wallet_id == Wallet.id)
    if not include_archived:
        stmt = stmt.where(Wallet.archived.is_(False))
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for holding, _ in db.execute(stmt):
        totals[holding.symbol] = money.add(
            totals.get(holding.symbol, Decimal(0)), Decimal(holding.amount)
        )
        counts[holding.symbol] = counts.get(holding.symbol, 0) + 1
    return [
        {"symbol": s, "total": money.format_amount(totals[s]), "wallets": counts[s]}
        for s in sorted(totals)
    ]


# ---- transfers ---------------------------------------------------------------------------


def _after_balance_check() -> None:
    """Test hook: lets tests hold a transfer between its balance check and its write."""


def check_route(src: Wallet, dst: Wallet, symbol: str) -> tuple[str | None, list[str]]:
    """Network rules for moving `symbol` from src to dst. Returns (network, warnings)."""
    if src.network and dst.network and src.network != dst.network:
        raise WalletError(
            409,
            f"{src.name} is on {networks.network_name(src.network)} and {dst.name} is on "
            f"{networks.network_name(dst.network)}. Sending between different networks loses "
            "the coins in real life; it needs a bridge, which is a separate, riskier step.",
        )
    check_coin_on_wallet(dst, symbol)
    warnings = []
    if "exchange" in (src.kind, dst.kind):
        warnings.append(EXCHANGE_REMINDER)
    return dst.network or src.network, warnings


def transfer(
    db: DbSession,
    src: Wallet,
    dst: Wallet,
    symbol: str,
    amount: Decimal,
    note: str,
    actor: User | None,
) -> tuple[Transfer, list[str]]:
    if src.id == dst.id:
        raise WalletError(422, "Pick two different wallets.")
    if amount <= 0:
        raise WalletError(422, "The amount must be more than zero.")
    require_active(src, "send from it")
    require_active(dst, "send to it")
    require_manual(db, src, "practise a transfer from it")
    require_manual(db, dst, "practise a transfer to it")
    network, warnings = check_route(src, dst, symbol)

    src_holding, available = balance(db, src, symbol)
    if available < amount:
        raise WalletError(
            409,
            f"{src.name} has {money.format_amount(available)} {symbol}, not enough to send "
            f"{money.format_amount(amount)}.",
        )
    _after_balance_check()

    remaining = money.subtract(available, amount)
    if remaining == 0:
        db.delete(src_holding)
    else:
        src_holding.amount = money.format_amount(remaining)
    dst_holding, current = balance(db, dst, symbol)
    credited = money.format_amount(money.add(current, amount))
    if dst_holding is None:
        db.add(Holding(wallet_id=dst.id, symbol=symbol, amount=credited))
    else:
        dst_holding.amount = credited

    record = Transfer(
        from_wallet_id=src.id,
        to_wallet_id=dst.id,
        from_wallet_name=src.name,
        to_wallet_name=dst.name,
        symbol=symbol,
        amount=money.format_amount(amount),
        network=network,
        simulated=True,
        note=note,
        user_id=actor.id if actor else None,
        username=actor.username if actor else None,
    )
    db.add(record)
    db.flush()
    return record, warnings


def move_everything(db: DbSession, src: Wallet, dst: Wallet, actor: User | None) -> list[Transfer]:
    """Move all of src's holdings to dst, all or nothing (the caller's transaction)."""
    require_manual(db, src, "move its coins")
    require_manual(db, dst, "move coins into it")
    holdings = holdings_of(db, src)
    problems = []
    for h in holdings:
        try:
            check_route(src, dst, h.symbol)
        except WalletError as e:
            problems.append(f"{h.symbol}: {e.message}")
    if problems:
        raise WalletError(
            409,
            f"Can't move everything from {src.name} to {dst.name}, so nothing was moved.",
            problems=problems,
        )
    note = f"Moved before deleting wallet {src.name}"
    return [transfer(db, src, dst, h.symbol, Decimal(h.amount), note, actor)[0] for h in holdings]


def serialize_transfer(t: Transfer) -> dict:
    return {
        "id": t.id,
        "created_at": t.created_at,
        "from_wallet_id": t.from_wallet_id,
        "to_wallet_id": t.to_wallet_id,
        "from_wallet_name": t.from_wallet_name,
        "to_wallet_name": t.to_wallet_name,
        "symbol": t.symbol,
        "amount": t.amount,
        "network": t.network,
        "simulated": t.simulated,
        "label": SIMULATED_LABEL,
        "note": t.note,
        "username": t.username,
    }
