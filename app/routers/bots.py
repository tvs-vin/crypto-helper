"""Paper trading (12d): bots, their orders and results, and the kill switch. See app/bots.py.

bots.view sees every bot (like wallets, bots are shared); bots.run creates, starts, pauses and
deletes them and re-arms the kill switch; bots.stop trips it. Everything that changes is audited.
"""

import csv
import io
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import backtest as bt
from app import bots as engine
from app import readiness
from app.audit import write_audit
from app.db import get_db
from app.deps import require_app, require_permission
from app.models import Bot, BotOrder, BotPoint, User
from app.prices.catalog import all_coins
from app.prices.service import PricesUnavailable
from app.prices.valuation import round_fiat
from app.timeutil import utcnow

router = APIRouter(prefix="/api/bots", tags=["bots"], dependencies=[Depends(require_app("bots"))])
view = require_permission("bots.view")
run = require_permission("bots.run")
stop = require_permission("bots.stop")


def _prices(request: Request, db: DbSession, bot: Bot):
    """Live prices for a bot's coins (for showing its value), or None."""
    prices = request.app.state.prices
    try:
        snap = prices.snapshot(db)
    except PricesUnavailable:
        return None
    if prices.practice or snap.stale:
        return None
    return engine.live_prices(snap, all_coins(db), bot.params["coins"], bot.params["currency"])


def _owner(db: DbSession, bot: Bot) -> str | None:
    u = db.get(User, bot.user_id) if bot.user_id else None
    return u.username if u else None


def _live_out(db: DbSession, bot: Bot) -> dict | None:
    if bot.mode != "live":
        return None
    from app.models import TradingKey

    key = db.get(TradingKey, bot.trading_key_id) if bot.trading_key_id else None
    return {
        "key_id": key.id if key else None,
        "key": f"{key.label} ({key.masked})" if key else None,
        "exchange": key.kind if key else None,
        "order_kind": bot.order_kind,
        "protection_pct": bot.protection_pct,
        "sending": db.scalar(
            select(func.count())
            .select_from(BotOrder)
            .where(BotOrder.bot_id == bot.id, BotOrder.status == "sending")
        ),
        "cap_cut": (bot.state or {}).get("cap_cut"),
    }


def _out(db: DbSession, bot: Bot, prices) -> dict:
    return {
        "id": bot.id,
        "mode": bot.mode,
        "live": _live_out(db, bot),
        "name": bot.name,
        "owner": _owner(db, bot),
        "text": bt.describe({**bot.params, "start": "now", "end": "on"}).replace(", now to on", ""),
        "params": bot.params,
        "limits": bot.limits,
        "status": bot.status,
        "status_reason": bot.status_reason,
        "currency": bot.params["currency"],
        "summary": engine.summary(bot, prices),
        "pending": db.scalar(
            select(func.count())
            .select_from(BotOrder)
            .where(BotOrder.bot_id == bot.id, BotOrder.status == "pending")
        ),
        "last_day": (bot.state or {}).get("last_day"),
        "created_at": bot.created_at.isoformat(timespec="seconds"),
    }


def _sees(me: User, bot: Bot) -> bool:
    """Paper bots are shared (bots.view); a live bot is its owner's (and super's): real money."""
    return bot.mode != "live" or me.is_super or bot.user_id == me.id


@router.get("")
def list_bots(request: Request, me: User = Depends(view), db: DbSession = Depends(get_db)):
    rows = db.scalars(select(Bot).order_by(Bot.id)).all()
    out = []
    for b in rows:
        if _sees(me, b):
            out.append(_out(db, b, _prices(request, db, b)))
    return {"kill": engine.kill_state(db), "bots": out, "max": engine.MAX_BOTS}


@router.get("/meta")
def meta(_: User = Depends(view), db: DbSession = Depends(get_db)):
    """The plan form's choices (the Backtester's: fee presets, coins with daily prices)."""
    from app.routers.backtests import meta_data

    return meta_data(db)


@router.get("/readiness")
def readiness_report(request: Request, _: User = Depends(view), db: DbSession = Depends(get_db)):
    """Project rule 10, checked: clean paper days, a kill switch drill, the limits self-check."""
    return readiness.report(db, test=request.app.state.readiness_test_clock)


class BotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    params: dict
    limits: dict = Field(default_factory=dict)
    # Live bots (13c): real money with a trading key.
    mode: str = Field(default="paper", pattern=r"^(paper|live)$")
    trading_key_id: int | None = None
    order_kind: str = Field(default="limit", pattern=r"^(limit|market)$")
    protection_pct: str = Field(default="1", max_length=8)


def _live_checks(request: Request, db: DbSession, me: User, body: BotIn, params: dict):
    """Everything a live bot needs before it exists. Returns (key, protection)."""
    from decimal import Decimal, InvalidOperation

    from app import live_bots, readiness
    from app import trading as tr
    from app.deps import effective_permissions
    from app.models import TradingKey

    if "live.trade" not in effective_permissions(me) or not me.totp_enabled:
        raise HTTPException(status_code=403, detail="Live bots need live.trade and 2FA")
    key = db.get(TradingKey, body.trading_key_id) if body.trading_key_id else None
    if key is None or not tr.may_see(me, key):
        raise HTTPException(status_code=422, detail="Choose one of your trading keys")
    if not tr.enabled(db, key.kind):
        raise HTTPException(status_code=409, detail="Live trading on that exchange is off")
    if not tr.first_order_done(key):
        raise HTTPException(
            status_code=409,
            detail="Place the key's first tiny order first (Live trading → the key)",
        )
    if params["currency"] != "usd":
        raise HTTPException(status_code=422, detail="Live bots trade in US dollars for now")
    if not readiness.report(db, test=request.app.state.readiness_test_clock)["live_allowed"]:
        raise HTTPException(
            status_code=409,
            detail="Ready for live trading isn't green yet (Paper trading): project rule 10",
        )
    try:
        protection = Decimal(body.protection_pct.strip())
        if not Decimal("0.1") <= protection <= Decimal("5"):
            raise InvalidOperation
    except InvalidOperation:
        raise HTTPException(
            status_code=422, detail="Price protection is between 0.1 and 5 %"
        ) from None
    room = tr.cap_of(me) - live_bots.owner_put_in(db, me.id)
    if Decimal(params["initial"]) > room:
        raise HTTPException(
            status_code=422,
            detail=f"Your cap leaves ${max(room, Decimal(0)):.2f} for live bots: lower the "
            "starting money (or ask an admin to raise your cap)",
        )
    return key, protection


@router.post("", status_code=201)
def create(body: BotIn, request: Request, me: User = Depends(run), db: DbSession = Depends(get_db)):
    from app.wallets import WalletError, guard

    try:
        params, limits = engine.validate(body.params, body.limits)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    name = body.name.strip()
    try:
        guard(name=name)  # free text: never a pasted seed phrase or key
    except WalletError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    if (db.scalar(select(func.count()).select_from(Bot)) or 0) >= engine.MAX_BOTS:
        raise HTTPException(status_code=409, detail=f"At most {engine.MAX_BOTS} bots")
    coins = all_coins(db)
    missing = [s for s in params["coins"] if s not in coins]
    if missing:
        raise HTTPException(status_code=422, detail=f"No coin {', '.join(missing)} here")
    killed = engine.kill_state(db)["tripped"]
    key, protection = (None, None)
    if body.mode == "live":
        key, protection = _live_checks(request, db, me, body, params)
    bot = Bot(
        user_id=me.id,
        name=name,
        params=params,
        limits=limits,
        account=engine.new_account(),
        state={},
        status="paused" if killed else "running",
        status_reason="the kill switch is tripped" if killed else None,
        mode=body.mode,
        trading_key_id=key.id if key else None,
        order_kind=body.order_kind,
        protection_pct=str(protection) if protection is not None else "1",
    )
    db.add(bot)
    db.flush()
    engine.start(db, bot, utcnow())
    what = f"LIVE ({key.kind}, {body.order_kind}) " if key else ""
    write_audit(
        db, request, "bots.create", user=me, detail=f"{what}{name}: {_out(db, bot, None)['text']}"
    )
    db.commit()
    return _out(db, bot, _prices(request, db, bot))


def _bot(db: DbSession, bot_id: int, me: User | None = None) -> Bot:
    bot = db.get(Bot, bot_id)
    if bot is None or (me is not None and not _sees(me, bot)):
        raise HTTPException(status_code=404, detail="No such bot")
    return bot


@router.get("/{bot_id}")
def detail(
    bot_id: int, request: Request, me: User = Depends(view), db: DbSession = Depends(get_db)
):
    bot = _bot(db, bot_id, me)
    orders = db.scalars(
        select(BotOrder).where(BotOrder.bot_id == bot.id).order_by(BotOrder.id.desc()).limit(200)
    ).all()
    cur = bot.params["currency"]
    points = db.scalars(
        select(BotPoint).where(BotPoint.bot_id == bot.id).order_by(BotPoint.at)
    ).all()
    return {
        **_out(db, bot, _prices(request, db, bot)),
        "orders": [
            {
                "id": o.id,
                "created_at": o.created_at.isoformat(timespec="seconds"),
                "decided_for": o.decided_for.isoformat() if o.decided_for else None,
                "side": o.side,
                "symbol": o.symbol,
                "requested": o.requested,
                "status": o.status,
                "filled_at": o.filled_at.isoformat(timespec="seconds") if o.filled_at else None,
                "price": o.price,
                "units": o.units,
                # to the cent on screen; the CSV keeps them exact
                "value": round_fiat(Decimal(o.value), cur) if o.value else None,
                "fee": round_fiat(Decimal(o.fee), cur) if o.fee else None,
                "note": o.note,
            }
            for o in orders
        ],
        "points": bt.thin(
            [
                {
                    "at": p.at.isoformat(timespec="seconds"),
                    "value": p.value,
                    "benchmark": p.benchmark,
                }
                for p in points
            ],
            1000,
        ),
    }


@router.post("/{bot_id}/start")
def start_bot(
    bot_id: int, request: Request, me: User = Depends(run), db: DbSession = Depends(get_db)
):
    bot = _bot(db, bot_id, me)
    if engine.kill_state(db)["tripped"]:
        raise HTTPException(status_code=409, detail="The kill switch is tripped: re-arm it first")
    if bot.status == "running":
        return _out(db, bot, None)
    if bot.mode == "live":
        from app import live_bots

        bot.status = "running"  # as it would be: is anything else in the way?
        why = live_bots.why_not(
            db, bot, request.app.state.readiness_test_clock, request.app.state.settings
        )
        bot.status = "paused"
        if why:
            raise HTTPException(status_code=409, detail=f"It can't trade: {why}")
    engine.resume(bot, utcnow())
    write_audit(db, request, "bots.start", user=me, detail=bot.name)
    db.commit()
    return _out(db, bot, _prices(request, db, bot))


@router.post("/{bot_id}/pause")
def pause_bot(
    bot_id: int, request: Request, me: User = Depends(run), db: DbSession = Depends(get_db)
):
    bot = _bot(db, bot_id, me)
    bot.status, bot.status_reason = "paused", f"paused by {me.username}"
    bot.state = {**(bot.state or {}), "paused_by": "user"}
    for o in db.scalars(
        select(BotOrder).where(BotOrder.bot_id == bot.id, BotOrder.status == "pending")
    ):
        o.status, o.note = "cancelled", "bot paused"
    write_audit(db, request, "bots.pause", user=me, detail=bot.name)
    db.commit()
    return _out(db, bot, None)


@router.delete("/{bot_id}", status_code=204)
def delete_bot(
    bot_id: int, request: Request, me: User = Depends(run), db: DbSession = Depends(get_db)
):
    bot = _bot(db, bot_id, me)
    sending = db.scalar(
        select(func.count())
        .select_from(BotOrder)
        .where(BotOrder.bot_id == bot.id, BotOrder.status == "sending")
    )
    if sending:
        raise HTTPException(
            status_code=409, detail="A real order is on its way: try again in a few minutes"
        )
    write_audit(db, request, "bots.delete", user=me, detail=bot.name)
    db.delete(bot)
    db.commit()


@router.get("/{bot_id}/orders.csv")
def orders_csv(bot_id: int, me: User = Depends(view), db: DbSession = Depends(get_db)):
    bot = _bot(db, bot_id, me)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "decided_for",
            "filled_at",
            "side",
            "symbol",
            "status",
            "units",
            "price",
            "value",
            "fee",
            "currency",
            "note",
        ]
    )
    for o in db.scalars(select(BotOrder).where(BotOrder.bot_id == bot.id).order_by(BotOrder.id)):
        w.writerow(
            [
                o.decided_for or "",
                o.filled_at.isoformat(timespec="seconds") if o.filled_at else "",
                o.side,
                o.symbol,
                o.status,
                o.units or "",
                o.price or "",
                o.value or "",
                o.fee or "",
                bot.params["currency"].upper(),
                o.note or "",
            ]
        )
    safe = "".join(c if c.isalnum() else "-" for c in bot.name)[:40] or "bot"
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="paper-{safe}.csv"'},
    )


class KillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=200)


def _reason(body: KillIn, default: str) -> str:
    """The reason goes to the audit log, notifications and Discord: never a pasted secret."""
    from app.wallets import WalletError, guard

    reason = body.reason.strip()
    try:
        guard(reason=reason)
    except WalletError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    return reason or default


@router.post("/kill")
def kill(body: KillIn, request: Request, me: User = Depends(stop), db: DbSession = Depends(get_db)):
    """Stop every bot now. Works whatever else is going on; needs a person to re-arm."""
    reason = _reason(body, f"stopped by {me.username}")
    engine.trip(db, request.app.state.hub, me.username, reason, user_id=me.id)
    db.commit()
    return {"kill": engine.kill_state(db)}


@router.post("/drill")
def drill(
    body: KillIn, request: Request, me: User = Depends(stop), db: DbSession = Depends(get_db)
):
    """A kill switch drill: trips it for real (every bot stops, waiting orders are cancelled),
    checks that, then asks the bot check to run (it must refuse). Re-arming completes it."""
    reason = _reason(body, f"drill by {me.username}")
    if not engine.trip(db, request.app.state.hub, me.username, reason, user_id=me.id, drill=True):
        raise HTTPException(status_code=409, detail="The kill switch is already tripped")
    db.commit()  # the bot check opens its own session
    answer = request.app.state.bot_job.tick()
    engine.drill_checked(db, answer)
    db.commit()
    return {"kill": engine.kill_state(db)}


@router.post("/selfcheck")
def run_selfcheck(request: Request, me: User = Depends(run), db: DbSession = Depends(get_db)):
    """The limits self-check: the real risk code on a throwaway database (never this one)."""
    result = readiness.selfcheck()
    readiness.save_selfcheck(db, result, me.username)
    failed = [r["name"] for r in result["results"] if not r["ok"]]
    detail = "passed" if result["passed"] else f"FAILED: {', '.join(failed)}"
    write_audit(db, request, "bots.selfcheck", user=me, detail=f"{detail} ({result['risk_code']})")
    db.commit()
    return result


class RearmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str


@router.post("/rearm")
def rearm(
    body: RearmIn, request: Request, me: User = Depends(run), db: DbSession = Depends(get_db)
):
    if body.confirm != "REARM":
        raise HTTPException(status_code=422, detail="Type REARM to confirm")
    if not engine.rearm(db, request.app.state.hub, me.username, user_id=me.id):
        raise HTTPException(status_code=409, detail="The kill switch isn't tripped")
    db.commit()
    return {"kill": engine.kill_state(db)}
