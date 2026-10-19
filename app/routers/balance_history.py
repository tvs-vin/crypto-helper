"""Balance history (milestone 11e): each wallet's value over time, and the portfolio's.

Values reveal holdings and prices, so reading needs wallets.view and prices.view (like
/api/portfolio). The recording settings need prices.manage, like price history's.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import balance_history as bh
from app.audit import write_audit
from app.db import get_db
from app.deps import effective_permissions, require_app, require_permission
from app.models import User, Wallet
from app.prices.catalog import FIATS
from app.timeutil import utcnow

router = APIRouter(prefix="/api/balance-history", tags=["balance history"])
view = require_permission("wallets.view")
manage = require_permission("prices.manage")
Days = Query(default=30, ge=1, le=36500)
Most = Query(default=1000, ge=2, le=bh.MAX_ROWS)


def _viewer(user: User = Depends(view)) -> User:
    if "prices.view" not in effective_permissions(user):
        raise HTTPException(status_code=403, detail="Permission denied")
    return user


def _fiat(user: User, fiat: str | None) -> str:
    f = (fiat or (user.preferences or {}).get("fiat", "usd")).lower()
    if f not in FIATS:
        raise HTTPException(status_code=422, detail=f"fiat must be one of {', '.join(FIATS)}")
    return f


@router.get("/portfolio", dependencies=[Depends(require_app("overview"))])
def portfolio(
    days: int = Days,
    fiat: str | None = None,
    include_archived: bool = False,
    most: int = Most,
    user: User = Depends(_viewer),
    db: DbSession = Depends(get_db),
):
    """The combined value of today's wallets (archived ones only if asked), oldest first."""
    f = _fiat(user, fiat)
    stmt = select(Wallet)
    if not include_archived:
        stmt = stmt.where(Wallet.archived.is_(False))
    rows = bh.portfolio_series(db, db.scalars(stmt).all(), f, utcnow() - timedelta(days=days))
    return {"fiat": f, "days": days, "change": bh.change(rows, f), "rows": bh.thin(rows, most)}


@router.get("/wallets", dependencies=[Depends(require_app("wallets"))])
def every_wallet(
    days: int = Days,
    fiat: str | None = None,
    most: int = Query(default=60, ge=2, le=500),
    user: User = Depends(_viewer),
    db: DbSession = Depends(get_db),
):
    """Every wallet's value (no coin details), thinned for small charts: {wallet id: rows}."""
    f = _fiat(user, fiat)
    since = utcnow() - timedelta(days=days)
    out = {}
    for w in db.scalars(select(Wallet)).all():
        rows = bh.wallet_series(db, w, f, since)
        out[str(w.id)] = [{"at": r["at"], "value": r["value"]} for r in bh.thin(rows, most)]
    return {"fiat": f, "days": days, "wallets": out}


@router.get("/wallets/{wallet_id}", dependencies=[Depends(require_app("wallets"))])
def one_wallet(
    wallet_id: int,
    days: int = Days,
    fiat: str | None = None,
    most: int = Most,
    user: User = Depends(_viewer),
    db: DbSession = Depends(get_db),
):
    f = _fiat(user, fiat)
    w = db.get(Wallet, wallet_id)
    if w is None:
        raise HTTPException(status_code=404, detail="No such wallet")
    rows = bh.wallet_series(db, w, f, utcnow() - timedelta(days=days))
    return {
        "wallet_id": w.id,
        "fiat": f,
        "days": days,
        "change": bh.change(rows, f),
        "rows": bh.thin(rows, most),
    }


@router.get("/settings")
def get_settings(
    _: User = Depends(require_permission("prices.view")), db: DbSession = Depends(get_db)
):
    """Like price history's settings: shown in Settings → Prices. Counts only, no values."""
    return {"settings": bh.load_settings(db).model_dump(), "stats": bh.stats(db)}


@router.put("/settings")
def put_settings(
    body: dict, request: Request, actor: User = Depends(manage), db: DbSession = Depends(get_db)
):
    try:
        new = bh.BalanceHistorySettings(**body)
    except (ValidationError, TypeError) as e:
        msgs = (
            [err["msg"].removeprefix("Value error, ") for err in e.errors()]
            if isinstance(e, ValidationError)
            else [str(e)]
        )
        raise HTTPException(status_code=422, detail="; ".join(msgs)) from None
    old = bh.load_settings(db).model_dump()
    bh.save_settings(db, new, actor.username)
    changed = {k: f"{old[k]} -> {v}" for k, v in new.model_dump().items() if old[k] != v}
    if changed:
        write_audit(
            db,
            request,
            "balances.history_settings",
            user=actor,
            detail="; ".join(f"{k}: {v}" for k, v in changed.items()),
        )
    db.commit()
    return {"settings": new.model_dump()}
