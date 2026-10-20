"""Your price alerts (prices.view, from the Overview window). See app/price_alerts.py."""

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import money
from app import price_alerts as pa
from app.audit import write_audit
from app.db import get_db
from app.deps import require_app, require_permission
from app.models import PriceAlert, User
from app.prices.catalog import FIATS, all_coins
from app.prices.service import PricesUnavailable

router = APIRouter(
    prefix="/api/price-alerts",
    tags=["price alerts"],
    dependencies=[Depends(require_app("overview", "alerts"))],
)
view = require_permission("prices.view")


def _out(a: PriceAlert, snap) -> dict:
    price, change = pa.quote(snap, a) if snap is not None else (None, None)
    return {
        "id": a.id,
        "symbol": a.symbol,
        "fiat": a.fiat,
        "kind": a.kind,
        "value": a.value,
        "text": pa.describe(a),
        # armed: waiting for its moment; fired: went off and waits for the price to cross back.
        "state": "armed" if a.armed else "fired" if a.last_fired_at else "waiting",
        "last_fired_at": a.last_fired_at.isoformat(timespec="seconds") if a.last_fired_at else None,
        "created_at": a.created_at.isoformat(timespec="seconds"),
        "price": money.format_amount(price) if price is not None else None,
        "change_24h": str(change) if change is not None else None,
    }


def _snap(request: Request, db: DbSession, fetch: bool = True):
    """Current prices; `fetch=False` (for requests that write) uses the last ones fetched."""
    prices = request.app.state.prices
    try:
        snap = prices.snapshot(db) if fetch else prices.last_snapshot
    except PricesUnavailable:
        return None
    return None if prices.practice else snap


@router.get("")
def list_alerts(request: Request, me: User = Depends(view), db: DbSession = Depends(get_db)):
    rows = db.scalars(
        select(PriceAlert).where(PriceAlert.user_id == me.id).order_by(PriceAlert.id)
    ).all()
    snap = _snap(request, db)
    return {"alerts": [_out(a, snap) for a in rows], "max": pa.MAX_PER_USER}


class NewAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=16)
    fiat: str = Field(min_length=3, max_length=8)
    kind: Literal["above", "below", "move"]
    value: str = Field(min_length=1, max_length=40)  # text, never a JSON number


@router.post("", status_code=201)
def create_alert(
    body: NewAlert, request: Request, me: User = Depends(view), db: DbSession = Depends(get_db)
):
    coin = all_coins(db).get(body.symbol.strip().upper())
    if coin is None:
        raise HTTPException(status_code=422, detail=f"No coin {body.symbol!r} here")
    fiat = body.fiat.lower()
    if fiat not in FIATS:
        raise HTTPException(status_code=422, detail=f"Currency is one of {', '.join(FIATS)}")
    try:
        value = money.parse_amount(body.value, allow_zero=False)
    except money.AmountError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if body.kind == "move" and not (pa.MOVE_MIN <= value <= pa.MOVE_MAX):
        raise HTTPException(
            status_code=422, detail=f"A move is {pa.MOVE_MIN} to {pa.MOVE_MAX} percent"
        )
    if pa.count(db, me.id) >= pa.MAX_PER_USER:
        raise HTTPException(
            status_code=409, detail=f"At most {pa.MAX_PER_USER} alerts each: delete one first"
        )
    a = PriceAlert(user_id=me.id, symbol=coin.symbol, coingecko_id=coin.coingecko_id, fiat=fiat,
                   kind=body.kind, value=money.format_amount(value), armed=True)  # fmt: skip
    snap = _snap(request, db, fetch=False)  # this request holds the write lock: never fetch
    if snap is not None and not snap.stale:
        price, change = pa.quote(snap, a)
        # Already true now: it fires the next time it happens, not straight away.
        a.armed = not pa.met(a.kind, Decimal(a.value), price, change)
    db.add(a)
    write_audit(db, request, "price_alert.create", user=me, detail=pa.describe(a))
    db.commit()
    return _out(a, snap)


@router.delete("/{alert_id}", status_code=204)
def delete_alert(
    alert_id: int, request: Request, me: User = Depends(view), db: DbSession = Depends(get_db)
):
    a = db.get(PriceAlert, alert_id)
    if a is None or a.user_id != me.id:
        raise HTTPException(status_code=404, detail="No such alert")
    write_audit(db, request, "price_alert.delete", user=me, detail=pa.describe(a))
    db.delete(a)
    db.commit()
