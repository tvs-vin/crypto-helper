"""The trade log (milestone 11d): trades imported read-only from connected exchanges, and the
CSV export for tax software. Needs wallets.view and the Trade log app."""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import tax_csv
from app.audit import write_audit
from app.db import begin_immediate, get_db
from app.deps import require_app, require_permission
from app.models import Trade, User

router = APIRouter(
    prefix="/api/trades", tags=["trades"], dependencies=[Depends(require_app("trades"))]
)
view = require_permission("wallets.view")
MAX_EXPORT = 200_000


def _out(t: Trade) -> dict:
    return {
        "id": t.id,
        "wallet_id": t.wallet_id,
        "exchange": t.exchange,
        "exchange_name": tax_csv.NAMES.get(t.exchange, t.exchange),
        "account": t.account,
        "trade_id": t.trade_id,
        "order_id": t.order_id,
        "time": t.time.isoformat(timespec="seconds"),
        "base": t.base,
        "quote": t.quote,
        "side": t.side,
        "amount": t.amount,
        "price": t.price,
        "total": t.total,
        "fee": t.fee,
        "fee_asset": t.fee_asset,
    }


def _filtered(wallet_id, asset, since: date | None, until: date | None, side):
    stmt = select(Trade)
    if wallet_id is not None:
        stmt = stmt.where(Trade.wallet_id == wallet_id)
    if asset:
        a = asset.strip().upper()
        stmt = stmt.where((Trade.base == a) | (Trade.quote == a))
    if since:
        stmt = stmt.where(Trade.time >= datetime.combine(since, time.min))
    if until:  # the whole day (UTC)
        stmt = stmt.where(Trade.time < datetime.combine(until + timedelta(days=1), time.min))
    if side:
        stmt = stmt.where(Trade.side == side)
    return stmt


Filters = {
    "wallet_id": Query(default=None),
    "asset": Query(default=None, max_length=16, pattern=r"^[A-Za-z0-9]{1,16}$"),
    "since": Query(default=None, description="YYYY-MM-DD, UTC"),
    "until": Query(default=None, description="YYYY-MM-DD, UTC (inclusive)"),
    "side": Query(default=None, pattern=r"^(buy|sell)$"),
}


@router.get("")
def list_trades(
    wallet_id: int | None = Filters["wallet_id"],
    asset: str | None = Filters["asset"],
    since: date | None = Filters["since"],
    until: date | None = Filters["until"],
    side: str | None = Filters["side"],
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = None,
    _: User = Depends(view),
    db: DbSession = Depends(get_db),
):
    """Newest first. Page with ?before_id=<the last id you saw>."""
    stmt = _filtered(wallet_id, asset, since, until, side)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    if before_id is not None:
        stmt = stmt.where(Trade.id < before_id)
    rows = db.scalars(stmt.order_by(Trade.time.desc(), Trade.id.desc()).limit(limit)).all()
    return {"trades": [_out(t) for t in rows], "total": total}


@router.get("/formats")
def formats(_: User = Depends(view)):
    return [{"id": k, "name": n, "note": note} for k, (n, note) in tax_csv.FORMATS.items()]


@router.get("/export")
def export(
    request: Request,
    format: str = Query(pattern=r"^[a-z]{3,16}$"),  # noqa: A002 (the file format)
    wallet_id: int | None = Filters["wallet_id"],
    asset: str | None = Filters["asset"],
    since: date | None = Filters["since"],
    until: date | None = Filters["until"],
    side: str | None = Filters["side"],
    me: User = Depends(view),
    db: DbSession = Depends(get_db),
):
    if format not in tax_csv.FORMATS:
        raise HTTPException(status_code=422, detail="Unknown format")
    stmt = _filtered(wallet_id, asset, since, until, side).order_by(Trade.time, Trade.id)
    rows = db.scalars(stmt.limit(MAX_EXPORT + 1)).all()
    if len(rows) > MAX_EXPORT:
        raise HTTPException(
            status_code=413, detail=f"More than {MAX_EXPORT} trades: narrow the dates"
        )
    body = tax_csv.render(format, rows)
    # Tax records leaving the app: written down, like any change.
    begin_immediate(db)
    write_audit(
        db,
        request,
        "trades.export",
        user=me,
        detail=f"{tax_csv.FORMATS[format][0]}: {len(rows)} trade(s)",
    )
    db.commit()
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="trades-{format}-{stamp}.csv"'},
    )
