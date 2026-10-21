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


def _out(db: DbSession, bot: Bot, prices) -> dict:
    return {
        "id": bot.id,
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


@router.get("")
def list_bots(request: Request, _: User = Depends(view), db: DbSession = Depends(get_db)):
    rows = db.scalars(select(Bot).order_by(Bot.id)).all()
    out = []
    for b in rows:
        out.append(_out(db, b, _prices(request, db, b)))
    return {"kill": engine.kill_state(db), "bots": out, "max": engine.MAX_BOTS}


@router.get("/meta")
def meta(_: User = Depends(view), db: DbSession = Depends(get_db)):
    """The plan form's choices (the Backtester's: fee presets, coins with daily prices)."""
    from app.routers.backtests import meta_data

    return meta_data(db)


class BotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    params: dict
    limits: dict = Field(default_factory=dict)


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
    bot = Bot(
        user_id=me.id,
        name=name,
        params=params,
        limits=limits,
        account=engine.new_account(),
        state={},
        status="paused" if killed else "running",
        status_reason="the kill switch is tripped" if killed else None,
    )
    db.add(bot)
    db.flush()
    engine.start(db, bot, utcnow())
    write_audit(
        db, request, "bots.create", user=me, detail=f"{name}: {_out(db, bot, None)['text']}"
    )
    db.commit()
    return _out(db, bot, _prices(request, db, bot))


def _bot(db: DbSession, bot_id: int) -> Bot:
    bot = db.get(Bot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="No such bot")
    return bot


@router.get("/{bot_id}")
def detail(bot_id: int, request: Request, _: User = Depends(view), db: DbSession = Depends(get_db)):
    bot = _bot(db, bot_id)
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
    bot = _bot(db, bot_id)
    if engine.kill_state(db)["tripped"]:
        raise HTTPException(status_code=409, detail="The kill switch is tripped: re-arm it first")
    if bot.status == "running":
        return _out(db, bot, None)
    bot.status, bot.status_reason = "running", None
    st = dict(bot.state or {})
    st.pop("day", None)  # a fresh day for the daily loss limit
    bot.state = st
    write_audit(db, request, "bots.start", user=me, detail=bot.name)
    db.commit()
    return _out(db, bot, _prices(request, db, bot))


@router.post("/{bot_id}/pause")
def pause_bot(
    bot_id: int, request: Request, me: User = Depends(run), db: DbSession = Depends(get_db)
):
    bot = _bot(db, bot_id)
    bot.status, bot.status_reason = "paused", f"paused by {me.username}"
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
    bot = _bot(db, bot_id)
    write_audit(db, request, "bots.delete", user=me, detail=bot.name)
    db.delete(bot)
    db.commit()


@router.get("/{bot_id}/orders.csv")
def orders_csv(bot_id: int, _: User = Depends(view), db: DbSession = Depends(get_db)):
    bot = _bot(db, bot_id)
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


@router.post("/kill")
def kill(body: KillIn, request: Request, me: User = Depends(stop), db: DbSession = Depends(get_db)):
    """Stop every bot now. Works whatever else is going on; needs a person to re-arm."""
    reason = body.reason.strip() or f"stopped by {me.username}"
    engine.trip(db, request.app.state.hub, me.username, reason, user_id=me.id)
    db.commit()
    return {"kill": engine.kill_state(db)}


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
