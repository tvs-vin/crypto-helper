"""Live bots (phase 4, 13c): the paper engine's plans with real orders.

A live bot decides exactly like a paper bot (app/bots.py, the backtester's own code); only its
orders differ. Each bot check, for live bots:

1. **Claim** (database locked, short): every waiting live order that may go now is marked
   `sending` with our own order id, and that's committed *before* anything is sent. What may
   go is checked here, for each order: the kill switch, the bot running, **readiness**
   (`live_allowed`, the real clock), the exchange switched on, the key there and its owner
   allowed to trade with it (live.trade, 2FA, active), the bot's limits, and for buys the
   owner's **cap**. A bot that fails one of these is paused with the reason.
2. **Send** (no lock): the exchange's market rules, `orders.prepare` (steps, price
   protection, minimums) and the order itself, immediate-or-cancel.
3. **Record** (locked): the real fill (coins, value, fee, from the exchange's own record of the
   order) goes into the bot's account; an order that couldn't go is cancelled with why.

An order whose answer was lost stays `sending`; a later check looks it up by our id (never
resends it). Live bots' money: `put_in` is what the bot was given. The owner's live bots
together may never be given more than the owner's cap (scheduled money is cut to fit), and
none buys while they're over it (if the cap was lowered). The exchange account must hold the
money: if it doesn't, the exchange refuses and the bot pauses.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import notifications as nt
from app import orders, readiness
from app import trading as tr
from app.audit import record
from app.bots import ACTOR, _d, kill_state, limit_buy
from app.models import Bot, BotOrder, TradingKey, User
from app.sync import SourceError, available

log = logging.getLogger(__name__)

LOOKUP_AFTER = timedelta(minutes=2)  # an order still "sending" this long: look it up
RECONCILE_EVERY = timedelta(hours=1)
UNKNOWN_TOO_LONG = timedelta(minutes=30)  # still unknown: the bot pauses (lookups go on)
PENDING_TOO_OLD = timedelta(days=1)  # a decision that couldn't be sent for a day is stale


def owner_put_in(db: DbSession, user_id: int | None) -> Decimal:
    """Money the owner's live bots have been given, together."""
    if user_id is None:
        return Decimal(0)
    bots = db.scalars(select(Bot).where(Bot.mode == "live", Bot.user_id == user_id))
    return sum((_d((b.account or {}).get("put_in")) for b in bots), Decimal(0))


def flow_room(db: DbSession, bot: Bot) -> Decimal:
    """How much more money the owner's cap lets their live bots be given."""
    owner = db.get(User, bot.user_id) if bot.user_id else None
    if owner is None:
        return Decimal(0)
    return max(Decimal(0), tr.cap_of(owner) - owner_put_in(db, owner.id))


def why_not(db: DbSession, bot: Bot, test_clock: bool, settings) -> str | None:
    """Why this live bot may not send an order now (None: it may). Rule 10 included."""
    if kill_state(db)["tripped"]:
        return "the kill switch is tripped"
    if bot.status != "running":
        return "the bot isn't running"
    if not readiness.report(db, test=test_clock)["live_allowed"]:
        return "Ready for live trading isn't green"
    key = db.get(TradingKey, bot.trading_key_id) if bot.trading_key_id else None
    if key is None:
        return "its trading key was deleted"
    if not tr.enabled(db, key.kind):
        return "live trading on its exchange is switched off"
    if not tr.first_order_done(key):
        return "its key hasn't had its first tiny order yet (Live trading)"
    if available(settings).get(key.kind) is None or orders.client_for(key.kind) is None:
        return "its exchange isn't available here"
    owner = db.get(User, bot.user_id) if bot.user_id else None
    if owner is None or not owner.is_active:
        return "its owner's account is gone or deactivated"
    if not tr.may_use(owner, key):
        return "its owner may no longer trade with that key (permissions or 2FA)"
    return None


def pause(db: DbSession, hub, bot: Bot, reason: str) -> None:
    """Pause a live bot (not running any more: its waiting orders are cancelled) and say why."""
    bot.status, bot.status_reason = "paused", reason[:200]
    bot.state = {**(bot.state or {}), "paused_by": "live"}
    for o in db.scalars(
        select(BotOrder).where(BotOrder.bot_id == bot.id, BotOrder.status == "pending")
    ):
        o.status, o.note = "cancelled", f"bot paused: {reason}"[:200]
    record(db, "bots.pause", user_id=None, username=ACTOR, detail=f"{bot.name}: {reason}"[:300])
    owner = db.get(User, bot.user_id) if bot.user_id else None
    if owner:
        nt.notify(
            db,
            hub,
            [owner],
            category="trading",
            level="warning",
            title=f"Live bot {bot.name} paused",
            body=reason[:300],
            link="bots",
        )


@dataclass
class Job:
    """One order to send (or look up), with everything needed outside the database."""

    order_id: int
    bot_id: int
    exchange: str
    creds: dict
    side: str
    symbol: str
    quote: str
    amount: Decimal  # money for buys, coins for sells
    price: Decimal | None
    kind: str
    protection: Decimal
    client_id: str
    lookup: bool = False  # an earlier answer was lost: find it, don't send


def claim(db, job_ctx, now: datetime, prices_by_bot: dict[int, dict]) -> list[Job]:
    """Step 1, locked: mark what may go now as sending (and commit before sending)."""
    jobs = []
    box = job_ctx.secret_box
    settings = job_ctx.settings
    # Answers lost earlier: look those orders up (whatever the kill switch says: they happened).
    for o in db.scalars(select(BotOrder).where(BotOrder.status == "sending")):
        if o.sent_at and now - o.sent_at < LOOKUP_AFTER:
            continue
        bot = db.get(Bot, o.bot_id)
        if bot and o.sent_at and now - o.sent_at > UNKNOWN_TOO_LONG and bot.status == "running":
            pause(
                db,
                job_ctx.hub,
                bot,
                "an order's outcome is still unknown after 30 minutes "
                "(the exchange can't be reached?): check it on the exchange; the app keeps "
                "looking it up",
            )
        key = db.get(TradingKey, bot.trading_key_id) if bot and bot.trading_key_id else None
        if key is None:
            o.status, o.note = "unknown", "its key was deleted before the outcome was known"
            continue
        jobs.append(
            Job(
                o.id,
                bot.id,
                key.kind,
                json.loads(box.decrypt(key.secret_encrypted)),
                o.side,
                o.symbol,
                "USD",
                _d(o.requested),
                None,
                bot.order_kind,
                _d(bot.protection_pct),
                o.client_id,
                lookup=True,
            )
        )
    for bot in db.scalars(select(Bot).where(Bot.mode == "live", Bot.status == "running")):
        waiting = db.scalars(
            select(BotOrder)
            .where(BotOrder.bot_id == bot.id, BotOrder.status == "pending")
            .order_by(BotOrder.id)
        ).all()
        for o in [o for o in waiting if now - o.created_at > PENDING_TOO_OLD]:
            o.status, o.note = (
                "cancelled",
                "too old (waited over a day): the next decision decides again",
            )
        waiting = [o for o in waiting if o.status == "pending"]
        if not waiting:
            continue
        why = why_not(db, bot, job_ctx.test_clock, settings)
        if why:
            pause(db, job_ctx.hub, bot, why)
            continue
        prices = prices_by_bot.get(bot.id)
        if prices is None:
            continue  # no live price for one of its coins: the orders wait
        key = db.get(TradingKey, bot.trading_key_id)
        creds = json.loads(box.decrypt(key.secret_encrypted))
        acct, st = dict(bot.account), dict(bot.state)
        today = now.date().isoformat()
        if st.get("spent_day") != today:
            st["spent_day"], st["spent"] = today, "0"
        over_cap = owner_put_in(db, bot.user_id) > tr.cap_of(db.get(User, bot.user_id))
        cash = _d(acct["cash"]) - _d(st.get("reserved"))
        for o in sorted(waiting, key=lambda o: (o.side != "sell", o.id)):
            if o.side == "sell":
                held = _d(acct["units"].get(o.symbol))
                amount = min(_d(o.requested), held)
                if amount <= 0:
                    o.status, o.note = "cancelled", "nothing to sell"
                    continue
            else:
                if over_cap:
                    o.status, o.note = "cancelled", "over your cap (it was lowered): no buys"
                    continue
                amount, notes = limit_buy(bot.limits or {}, st, _d(o.requested), cash)
                amount = min(amount, cash)
                # The exchange's fee comes on top of what's bought: leave room for it (the plan's
                # fee estimate), so the bot never spends more than its cash.
                amount = (amount / (1 + _d(bot.params.get("fee_pct")) / 100)).quantize(
                    Decimal("0.01"), rounding="ROUND_DOWN"
                )
                if notes:
                    o.note = "; ".join(notes)[:200]
                if amount <= 0:
                    o.status = "cancelled"
                    o.note = (o.note or "no cash left to spend")[:200]
                    continue
                cash -= amount
                st["spent"] = str(_d(st.get("spent")) + amount)  # counts once it's sent
            o.status, o.sent_at = "sending", now
            o.client_id = orders.new_client_id()
            o.requested = str(amount)
            jobs.append(
                Job(
                    o.id,
                    bot.id,
                    key.kind,
                    creds,
                    o.side,
                    o.symbol,
                    "USD",
                    amount,
                    prices[o.symbol],
                    bot.order_kind,
                    _d(bot.protection_pct),
                    o.client_id,
                )
            )
        st["reserved"] = str(_d(acct["cash"]) - cash)  # cash promised to orders being sent
        bot.state = st
    return jobs


def send(job: Job) -> tuple[str, object]:
    """Step 2, no lock. Returns (outcome, detail): "fill" (a Fill), "none" (not sent, or
    nothing filled), "retry" (nothing was sent: the exchange couldn't be reached, try again),
    "unknown" (it may have gone through: look it up later), "refused" (the exchange said no)."""
    client = orders.client_for(job.exchange)
    try:  # before anything is sent: a failure here means nothing went out
        rules = client.rules(job.symbol, job.quote)
    except SourceError as e:
        return ("retry" if orders.transient(e) else "refused"), str(e)
    except orders.OrderError as e:
        return "refused", str(e)
    if job.lookup:
        o = orders.Order(
            job.client_id, job.symbol, job.quote, job.side, job.kind, symbol=rules.symbol
        )
        try:
            found = client.lookup(job.creds, o)
        except (orders.OrderError, SourceError) as e:  # still can't tell: look again later
            return "unknown", f"couldn't look it up: {e}"
        return ("fill", found) if found else ("none", "it never reached the exchange")
    try:
        order = orders.prepare(
            rules,
            base=job.symbol,
            quote=job.quote,
            side=job.side,
            kind=job.kind,
            price=job.price,
            spend=job.amount if job.side == "buy" else None,
            units=job.amount if job.side == "sell" else None,
            protection_pct=job.protection,
            client_id=job.client_id,
        )
    except orders.OrderError as e:
        return "none", str(e)
    try:
        return "fill", client.place(job.creds, order)
    except orders.OrderError as e:
        if e.unknown:
            return "unknown", str(e)
        if e.final:  # the key itself was refused: deleted on the exchange, or not this address
            return "refused", (
                f"{e} (the key was deleted on the exchange, or this server's address isn't on "
                "its allowlist any more)"
            )
        return "refused", str(e)
    except SourceError as e:  # (clients turn these into OrderErrors; just in case)
        return ("unknown" if orders.transient(e) else "refused"), str(e)


def record_result(db, hub, job: Job, outcome: str, result, now: datetime) -> bool:
    """Step 3, locked: the outcome into the order and the bot's account. True if it filled."""
    o = db.get(BotOrder, job.order_id)
    bot = db.get(Bot, job.bot_id)
    if o is None or bot is None:
        return False
    st = dict(bot.state or {})
    if outcome == "unknown":  # its cash stays reserved until the lookup knows what happened
        o.note = f"outcome unknown, will look it up: {result}"[:200]
        return False
    if outcome == "retry":  # nothing was sent: back in the queue, its cash free again
        o.status, o.client_id, o.sent_at = "pending", None, None
        o.note = f"the exchange couldn't be reached; trying again: {result}"[:200]
        if job.side == "buy":
            st["reserved"] = str(max(Decimal(0), _d(st.get("reserved")) - job.amount))
            st["spent"] = str(max(Decimal(0), _d(st.get("spent")) - job.amount))
        bot.state = st
        return False
    if job.side == "buy":  # the cash this order reserved is free again (or spent, below)
        st["reserved"] = str(max(Decimal(0), _d(st.get("reserved")) - job.amount))
    if outcome in ("none", "refused"):
        o.status, o.note = "cancelled", str(result)[:200]
        if job.side == "buy":  # nothing was spent after all
            st["spent"] = str(max(Decimal(0), _d(st.get("spent")) - job.amount))
        bot.state = st
        if outcome == "refused" and bot.status == "running":
            pause(db, hub, bot, f"the exchange refused an order: {result}")
        return False
    fill = result
    acct = dict(bot.account)
    sym, quote = job.symbol, job.quote
    fee_q = fill.fee if fill.fee_asset == quote else Decimal(0)
    fee_b = fill.fee if fill.fee_asset == sym else Decimal(0)
    units = {s: _d(u) for s, u in acct["units"].items()}
    cost = {s: _d(c) for s, c in acct["cost"].items()}
    if fill.base > 0 and job.side == "buy":
        acct["cash"] = str(_d(acct["cash"]) - fill.value - fee_q)
        units[sym] = units.get(sym, Decimal(0)) + fill.base - fee_b
        cost[sym] = cost.get(sym, Decimal(0)) + fill.value + fee_q
    elif fill.base > 0:
        held = units.get(sym, Decimal(0))
        avg = cost.get(sym, Decimal(0)) / held if held else Decimal(0)
        acct["cash"] = str(_d(acct["cash"]) + fill.value - fee_q)
        units[sym] = held - fill.base - fee_b
        cost[sym] = cost.get(sym, Decimal(0)) - avg * fill.base
        acct["realized"] = str(_d(acct["realized"]) + fill.value - fee_q - avg * fill.base)
    if fill.base > 0:
        acct["fees"] = str(_d(acct["fees"]) + fee_q)
        acct["units"] = {s: str(u) for s, u in units.items()}
        acct["cost"] = {s: str(c) for s, c in cost.items()}
        bot.account = acct
    if job.side == "buy":  # count what was really spent today
        spent = fill.value + fee_q
        st["spent"] = str(max(Decimal(0), _d(st.get("spent")) - job.amount + spent))
    bot.state = st
    o.exchange_order_id = fill.order_id
    o.fee_asset = fill.fee_asset
    o.filled_at = now
    if fill.base > 0:
        o.status = "filled" if fill.status == "filled" else "partial"
        o.units, o.value, o.fee = str(fill.base), str(fill.value), str(fill.fee)
        o.price = str(fill.avg_price) if fill.avg_price else None
        if fill.fee_asset not in (quote, sym):
            o.note = f"fee charged in {fill.fee_asset}: not taken from the bot's cash"
    else:
        o.status, o.note = "cancelled", "nothing filled: the price moved past the protection"
    return fill.base > 0


def reconcile(db, hub, bots_by_key: dict, balances: dict[int, dict]) -> int:
    """The exchange's balances against what live bots think they hold (locked). A key whose
    account holds less of a coin than its bots do: those bots pause. Returns how many."""
    paused = 0
    for key_id, held in balances.items():
        bots = bots_by_key.get(key_id) or []
        need: dict[str, Decimal] = {}
        for b in bots:
            for s, u in ((db.get(Bot, b).account or {}).get("units") or {}).items():
                need[s] = need.get(s, Decimal(0)) + _d(u)
        short = [
            s for s, n in need.items() if n > 0 and held.get(s, Decimal(0)) < n * Decimal("0.999")
        ]
        if not short:
            continue
        for b in bots:
            bot = db.get(Bot, b)
            if bot.status == "running":
                pause(
                    db,
                    hub,
                    bot,
                    f"the exchange holds less {', '.join(short)} than the bots "
                    "think (sold or moved by hand?): check, then start it again",
                )
                paused += 1
    return paused


def run(ctx, now: datetime, prices_by_bot: dict[int, dict]) -> dict:
    """One pass for live bots: claim (locked), send (no lock), record (locked), and once an
    hour the exchanges' balances against the bots'. `ctx` is the BotJob. `prices_by_bot`
    empty: nothing new is sent (only lost answers are looked up)."""
    from app import live
    from app.db import IMMEDIATE

    with ctx.factory() as db:
        db.connection(execution_options={IMMEDIATE: True})
        jobs = claim(db, ctx, now, prices_by_bot)
        db.commit()
    out = {"sent": 0, "filled": 0, "unknown": 0}
    if jobs:
        results = [(j, *send(j)) for j in jobs]  # the network, with nothing locked
        filled: dict[int, list[int]] = {}
        with ctx.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            for j, outcome, res in results:
                out["sent"] += not j.lookup
                out["unknown"] += outcome == "unknown"
                if record_result(db, ctx.hub, j, outcome, res, now):
                    filled.setdefault(j.bot_id, []).append(j.order_id)
                    out["filled"] += 1
            for bot_id, ids in filled.items():
                _tell(db, ctx.hub, db.get(Bot, bot_id), [db.get(BotOrder, i) for i in ids])
            db.commit()
        live.publish(ctx.hub, ctx.factory, ["bots"])
    if now - getattr(ctx, "last_reconcile", datetime.min) >= RECONCILE_EVERY:
        ctx.last_reconcile = now
        out["paused"] = _reconcile(ctx)
    return out


def _tell(db, hub, bot: Bot, filled: list[BotOrder]) -> None:
    owner = db.get(User, bot.user_id) if bot.user_id else None
    if owner is None:
        return
    lines = [
        f"{o.side} {o.symbol}"
        + nt.detail("amounts", f" {o.units}")
        + nt.detail("values", f" for {_d(o.value):.2f} USD")
        + (f" ({o.note})" if o.note else "")
        for o in filled
    ]
    nt.notify(
        db,
        hub,
        [owner],
        category="trading",
        title=f"Live bot {bot.name}: {len(filled)} real order(s) filled",
        body="; ".join(lines) + ".",
        link="bots",
    )


def _reconcile(ctx) -> int:
    from app.db import IMMEDIATE

    with ctx.factory() as db:
        live_bots = db.scalars(select(Bot).where(Bot.mode == "live", Bot.status == "running"))
        by_key: dict[int, list[int]] = {}
        for b in live_bots:
            if b.trading_key_id:
                by_key.setdefault(b.trading_key_id, []).append(b.id)
        keys = {k: db.get(TradingKey, k) for k in by_key}
        creds = {
            k: (v.kind, json.loads(ctx.secret_box.decrypt(v.secret_encrypted)))
            for k, v in keys.items()
            if v
        }
    balances = {}
    for key_id, (kind, c) in creds.items():  # reading balances: no lock held
        ex = available(ctx.settings).get(kind)
        try:
            fetched = ex.fetch(c).balances
        except SourceError as e:
            log.warning("live bots: couldn't read balances for key %s: %s", key_id, e)
            continue
        balances[key_id] = {ex.aliases.get(code, code): v for code, v in fetched.items()}
    if not balances:
        return 0
    with ctx.factory() as db:
        db.connection(execution_options={IMMEDIATE: True})
        paused = reconcile(db, ctx.hub, by_key, balances)
        db.commit()
    return paused
