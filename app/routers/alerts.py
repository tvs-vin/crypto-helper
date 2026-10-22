"""Your alerts (12a): portfolio, wallet, drift and trend (app/smart_alerts.py), in the Alerts
window. Each kind needs its own permissions (smart_alerts.NEEDS); everyone only sees and changes
their own."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import smart_alerts as sa
from app.audit import write_audit
from app.db import get_db
from app.deps import effective_permissions, require_app, require_permission
from app.models import Alert, User, Wallet, WalletSource
from app.prices import daily
from app.prices.catalog import all_coins

router = APIRouter(tags=["alerts"])
view = require_permission("prices.view")
in_app = [Depends(require_app("alerts"))]


def _names(db: DbSession) -> dict[int, str]:
    return {w.id: w.nickname or w.name for w in db.scalars(select(Wallet))}


def _out(a: Alert, names) -> dict:
    return {
        "id": a.id,
        "kind": a.kind,
        "params": a.params,
        "text": sa.describe(a, names),
        "state": "armed" if a.armed else "fired",
        "note": a.state.get("note"),
        "side": a.state.get("side"),
        "last_fired_at": a.last_fired_at.isoformat(timespec="seconds") if a.last_fired_at else None,
        "created_at": a.created_at.isoformat(timespec="seconds"),
    }


@router.get("/api/alerts", dependencies=in_app)
def list_alerts(me: User = Depends(view), db: DbSession = Depends(get_db)):
    perms = effective_permissions(me)
    rows = db.scalars(select(Alert).where(Alert.user_id == me.id).order_by(Alert.id)).all()
    names = _names(db) if "wallets.view" in perms else {}
    synced = (
        [
            {"id": w.id, "name": w.nickname or w.name}
            for w in db.scalars(
                select(Wallet).join(WalletSource, WalletSource.wallet_id == Wallet.id)
            )
        ]
        if "wallets.view" in perms
        else []
    )
    cov = daily.coverage(db)
    return {
        "alerts": [_out(a, names) for a in rows],
        "max": sa.MAX_PER_USER,
        "kinds": [k for k in sa.KINDS if sa.allowed(me, k)],
        "synced_wallets": synced,
        "daily": {
            s: {"first": c["first"], "last": c["last"], "days": c["days"]} for s, c in cov.items()
        },
        "coins": sorted(all_coins(db)),
    }


class NewAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["portfolio", "wallet", "drift", "trend"]
    params: dict


@router.post("/api/alerts", status_code=201, dependencies=in_app)
def create_alert(
    body: NewAlert, request: Request, me: User = Depends(view), db: DbSession = Depends(get_db)
):
    if not sa.allowed(me, body.kind):
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        params = sa.PARAMS[body.kind](**body.params).model_dump()
    except ValidationError as e:
        msg = "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors())
        raise HTTPException(status_code=422, detail=msg) from None
    coins = all_coins(db)
    if body.kind == "trend" and params["symbol"] not in coins:
        raise HTTPException(status_code=422, detail=f"No coin {params['symbol']!r} here")
    if body.kind == "drift":
        unknown = [s for s in params["targets"] if s not in coins]
        if unknown:
            raise HTTPException(status_code=422, detail=f"No coin {', '.join(unknown)} here")
    if body.kind == "wallet" and params["wallet_id"] is not None:
        if db.get(WalletSource, params["wallet_id"]) is None:
            raise HTTPException(
                status_code=422, detail="That wallet doesn't sync: pick a synced one"
            )
    if sa.count(db, me.id) >= sa.MAX_PER_USER:
        raise HTTPException(status_code=409, detail=f"At most {sa.MAX_PER_USER} alerts each")
    a = Alert(user_id=me.id, kind=body.kind, params=params, state={}, armed=True)
    db.add(a)
    db.flush()
    write_audit(db, request, "alerts.create", user=me, detail=sa.describe(a, _names(db)))
    db.commit()
    return _out(a, _names(db))


@router.delete("/api/alerts/{alert_id}", status_code=204, dependencies=in_app)
def delete_alert(
    alert_id: int, request: Request, me: User = Depends(view), db: DbSession = Depends(get_db)
):
    a = db.get(Alert, alert_id)
    if a is None or a.user_id != me.id:
        raise HTTPException(status_code=404, detail="No such alert")
    write_audit(db, request, "alerts.delete", user=me, detail=sa.describe(a, _names(db)))
    db.delete(a)
    db.commit()


@router.get("/api/prices/daily", dependencies=[Depends(require_app("alerts", "overview"))])
def daily_prices(
    symbol: str = Query(max_length=16),
    days: int = Query(default=365, ge=1, le=10000),
    _: User = Depends(view),
    db: DbSession = Depends(get_db),
):
    """Daily USD prices from Coinbase's history, oldest first."""
    rows = daily.recent(db, symbol.strip().upper(), days)
    return {
        "symbol": symbol.strip().upper(),
        "rows": [
            {"day": c.day, "open": c.open, "high": c.high, "low": c.low, "close": c.close}
            for c in rows
        ],
    }
