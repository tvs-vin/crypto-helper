"""Syncing one wallet, and the background job that syncs every wallet when it's due.

1. A short session reads the wallet's source and decrypts its credentials.
2. With no session open, the key is checked (still read-only?) and the balances are read.
3. The write lock is taken only to apply them and record how it went.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import money
from app import notifications as nt
from app import wallets as svc
from app.audit import record
from app.models import AppSetting, Connection, User, Wallet, WalletSource
from app.prices.catalog import all_coins
from app.sync import Exchange, Fetched, SourceError, available, chains
from app.timeutil import utcnow

log = logging.getLogger(__name__)

SETTINGS_KEY = "sync"
NOTIFY_AFTER = 3  # failures in a row before people are told (a revoked key: at once)
TICK_SECONDS = 60
ACTOR = "<sync>"
TRADES_EVERY = 3600  # seconds between automatic trade imports (Sync now always imports)


class SyncSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    interval_minutes: int = Field(default=15, ge=5, le=1440)


def load_settings(db: DbSession) -> SyncSettings:
    row = db.get(AppSetting, SETTINGS_KEY)
    return SyncSettings(**row.value) if row else SyncSettings()


def save_settings(db: DbSession, s: SyncSettings, actor: str | None) -> None:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        db.add(AppSetting(key=SETTINGS_KEY, value=s.model_dump(), updated_by=actor))
    else:
        row.value, row.updated_by = s.model_dump(), actor


@dataclass
class Result:
    ok: bool
    changes: list[str] = field(default_factory=list)
    error: str | None = None
    new_trades: int = 0


def credentials(secret_box, conn: Connection) -> dict:
    return json.loads(secret_box.decrypt(conn.secret_encrypted))


def refused_message(exchange: Exchange) -> str:
    return (
        f"This {exchange.name} key can trade or move funds, so it's refused: Crypto Helper only "
        f"accepts view-only keys. Delete the key on {exchange.name} and add a new one with view "
        "permission only."
    )


def people(db: DbSession) -> list[User]:
    """Who hears about sync problems: super and anyone who manages connections."""
    from app.deps import effective_permissions

    return [
        u for u in nt.everyone(db) if u.is_super or "wallets.connect" in effective_permissions(u)
    ]


# ---- one wallet ----------------------------------------------------------------------------


def _read(exchange: Exchange, creds: dict) -> Fetched:
    """The network part: the key must still be read-only, then the balances."""
    check = exchange.check(creds)
    if check.read_only is False:
        raise SourceError(refused_message(exchange), final=True)
    return exchange.fetch(creds)


def apply(db: DbSession, wallet: Wallet, aliases: dict[str, str], fetched: Fetched, diffs=None):
    """Make the wallet's holdings match what the source reported. Returns (changes, untracked).
    Assets the app doesn't track are listed, not added (no spam tokens). Each change is also
    appended to `diffs` as (symbol, old, new) amounts, for wallet alerts."""
    coins = all_coins(db)
    want: dict[str, Decimal] = {}
    untracked = []
    for asset, amount in sorted(fetched.balances.items()):
        if amount <= 0:
            continue
        code = asset.strip().upper()
        symbol = aliases.get(code, code)
        if symbol in coins:
            want[symbol] = money.add(want.get(symbol, Decimal(0)), amount)
        else:
            untracked.append({"asset": code, "amount": money.format_amount(amount)})
    current = {h.symbol: Decimal(h.amount) for h in svc.holdings_of(db, wallet)}
    changes = []
    for symbol in sorted(set(want) | set(current)):
        new = want.get(symbol, Decimal(0))
        if current.get(symbol, Decimal(0)) == new:
            continue
        try:
            old, new_text = svc.set_holding(db, wallet, symbol, new)
        except svc.WalletError as e:  # e.g. a coin that can't be on this wallet's network
            untracked.append(
                {"asset": symbol, "amount": money.format_amount(new), "why": e.message}
            )
            continue
        changes.append(f"{symbol}: {old} -> {new_text}")
        if diffs is not None:
            diffs.append((symbol, current.get(symbol, Decimal(0)), new))
    return changes, untracked


def sync_wallet(state, wallet_id: int, actor: User | None = None) -> Result:
    """Sync one wallet now. `state` is the app's state (settings, session factory, secret box,
    hub). `actor`: who pressed Sync now (None: the background job)."""
    factory, settings = state.session_factory, state.settings
    with factory() as db:
        source = db.get(WalletSource, wallet_id)
        wallet = db.get(Wallet, wallet_id)
        if source is None or wallet is None or wallet.archived:
            return Result(False, error="This wallet isn't synced")
        exchange = creds = watch = chain_settings = None
        network = wallet.network
        trade_state = dict((source.options or {}).get("trades") or {})
        last_trades = (source.options or {}).get("trades_at")
        coins = set(all_coins(db))
        if source.kind == "onchain":
            watch = chains.Watch.load(state.secret_box.decrypt(source.watch_encrypted))
            chain_settings = chains.load_settings(db)
        else:
            conn = db.get(Connection, source.connection_id) if source.connection_id else None
            exchange = available(settings).get(conn.kind) if conn else None
            creds = credentials(state.secret_box, conn) if conn and exchange else None
    info = {}
    try:  # no database session open from here until the balances are applied
        if watch is not None:
            got = chains.read(network, watch, chain_settings)
            fetched, aliases, info = Fetched(got.balances), {}, got.info
        elif exchange is None:
            raise SourceError("Its connection is missing or not available here", final=True)
        else:
            fetched, aliases = _read(exchange, creds), exchange.aliases
        error, final = None, False
    except SourceError as e:
        fetched, error, final = None, str(e), e.final
    except Exception as e:  # a bug or an unexpected answer must not stop other wallets
        log.exception("sync of wallet %s failed", wallet_id)
        fetched, error, final = None, f"Unexpected error: {type(e).__name__}", False
    trades, trade_error = None, None
    if error is None and exchange is not None and _trades_due(last_trades, actor):
        try:  # still no session open
            hint = coins | {a.upper() for a in fetched.balances}
            hint |= {code for code, sym in exchange.aliases.items() if sym in hint}
            trades, trade_state = exchange.trades(creds, trade_state, hint)
        except NotImplementedError:
            pass
        except SourceError as e:
            trade_error = str(e)
        except Exception as e:
            log.exception("trade import for wallet %s failed", wallet_id)
            trade_error = f"Unexpected error: {type(e).__name__}"

    from app.db import IMMEDIATE

    with factory() as db:
        db.connection(execution_options={IMMEDIATE: True})
        source, wallet = db.get(WalletSource, wallet_id), db.get(Wallet, wallet_id)
        if source is None or wallet is None:  # unlinked meanwhile
            return Result(False, error="This wallet isn't synced any more")
        now = utcnow()
        source.last_try_at = now
        hub = getattr(state, "hub", None)
        if error is None:
            diffs: list = []
            try:
                changes, untracked = apply(db, wallet, aliases, fetched, diffs)
            except money.AmountError as e:
                db.rollback()
                return _failed(
                    state,
                    wallet_id,
                    f"The exchange reported an amount that can't be stored: {e}",
                    False,
                )
            was_told = source.options.get("notified")
            first_sync = source.last_ok_at is None  # everything "arrives": not news
            source.last_ok_at, source.last_error, source.failures = now, None, 0
            source.untracked = untracked
            source.options = {**source.options, "notified": False, "info": info}
            new_trades = 0
            if trades is not None or trade_error:
                new_trades = store_trades(db, wallet, exchange, trades or [])
                source.options = {
                    **source.options,
                    "trades": trade_state,
                    "trades_at": now.isoformat(),
                    "trades_error": trade_error,
                }
                if new_trades:
                    record(
                        db,
                        "trades.import",
                        user_id=actor.id if actor else None,
                        username=actor.username if actor else ACTOR,
                        detail=f"{wallet.name} (id {wallet.id}): {new_trades} new trade(s)",
                    )
            if changes:
                record(
                    db,
                    "wallet.sync",
                    user_id=actor.id if actor else None,
                    username=actor.username if actor else ACTOR,
                    detail=f"{wallet.name} (id {wallet.id}): " + "; ".join(changes),
                )
            if diffs and not first_sync:
                from app import smart_alerts

                prices = getattr(state, "prices", None)  # never fetched here (we hold the lock)
                snap = prices.last_snapshot if prices and not prices.practice else None
                smart_alerts.wallet_changed(db, hub, wallet, diffs, snap)
            if was_told:
                nt.notify(
                    db,
                    hub,
                    people(db),
                    category="system",
                    level="info",
                    title=f"{wallet.name} syncs again",
                    link="wallets",
                )
            db.commit()
            return Result(True, changes, new_trades=new_trades)
        db.commit()
    return _failed(state, wallet_id, error, final)


def _failed(state, wallet_id: int, error: str, final: bool) -> Result:
    from app.db import IMMEDIATE

    with state.session_factory() as db:
        db.connection(execution_options={IMMEDIATE: True})
        source, wallet = db.get(WalletSource, wallet_id), db.get(Wallet, wallet_id)
        if source is None or wallet is None:
            return Result(False, error=error)
        source.last_try_at = utcnow()
        source.last_error = error[:300]
        source.failures += 1
        due = final or source.failures >= NOTIFY_AFTER
        if due and not source.options.get("notified"):
            nt.notify(
                db,
                getattr(state, "hub", None),
                people(db),
                category="system",
                level="warning",
                title=f"{wallet.name} can't sync",
                body=f"{error} Its balances stay as they were.",
                link="wallets",
            )
            source.options = {**source.options, "notified": True}
        db.commit()
    return Result(False, error=error)


def _trades_due(last: str | None, actor) -> bool:
    if actor is not None or not last:
        return True
    from datetime import datetime

    return (utcnow() - datetime.fromisoformat(last)).total_seconds() >= TRADES_EVERY


def store_trades(db: DbSession, wallet: Wallet, exchange: Exchange, rows) -> int:
    """Add the trades the log doesn't have yet (in the caller's write transaction)."""
    from app.models import Trade

    if not rows:
        return 0
    ids = {r.trade_id for r in rows}
    have = set(
        db.scalars(
            select(Trade.trade_id).where(Trade.wallet_id == wallet.id, Trade.trade_id.in_(ids))
        )
    )
    fmt = money.format_amount
    q18 = Decimal(1).scaleb(-18)
    added = 0
    for r in rows:
        if r.trade_id in have:
            continue
        have.add(r.trade_id)
        db.add(
            Trade(
                wallet_id=wallet.id,
                exchange=exchange.id,
                account=wallet.name[:64],
                trade_id=r.trade_id[:100],
                order_id=(r.order_id or None) and str(r.order_id)[:100],
                time=r.time,
                base=r.base[:16],
                quote=r.quote[:16],
                side=r.side,
                amount=fmt(r.amount.quantize(q18)),
                price=fmt(r.price.quantize(q18)),
                total=fmt(r.total.quantize(q18)),
                fee=fmt(r.fee.quantize(q18)),
                fee_asset=r.fee_asset[:16],
            )
        )
        added += 1
    return added


# ---- the background job --------------------------------------------------------------------


def due(db: DbSession, s: SyncSettings, now=None) -> list[int]:
    now = now or utcnow()
    cutoff = now - timedelta(minutes=s.interval_minutes)
    rows = db.execute(
        select(WalletSource.wallet_id, WalletSource.last_try_at)
        .join(Wallet, Wallet.id == WalletSource.wallet_id)
        .where(Wallet.archived.is_(False))
        .order_by(WalletSource.wallet_id)
    ).all()
    return [wid for wid, last in rows if last is None or last <= cutoff]


class SyncJob:
    def __init__(self, state):
        self.state = state

    def tick(self) -> list[int]:
        with self.state.session_factory() as db:
            s = load_settings(db)
            ids = due(db, s) if s.enabled else []
        for wallet_id in ids:  # one at a time: kind to the exchanges' rate limits
            sync_wallet(self.state, wallet_id)
        return ids

    async def run_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # one bad pass must never stop syncing for good
                log.exception("sync pass failed")
            await asyncio.sleep(TICK_SECONDS)
