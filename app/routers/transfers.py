from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from app import money
from app import wallets as svc
from app.audit import write_audit
from app.db import begin_immediate, get_db
from app.deps import require_app, require_permission
from app.models import Transfer, User, Wallet

router = APIRouter(tags=["transfers"])


class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_wallet_id: int
    to_wallet_id: int
    symbol: str = Field(max_length=16)
    amount: object  # validated by app.money (must be text)
    note: str = Field(default="", max_length=500)


@router.get("/api/transfers", dependencies=[Depends(require_app("transfers"))])
def list_transfers(
    limit: int = Query(default=100, ge=1, le=1000),
    before_id: int | None = None,
    wallet_id: int | None = None,
    _: User = Depends(require_permission("wallets.view")),
    db: DbSession = Depends(get_db),
):
    """Newest first. Page with ?before_id=<last id you saw>."""
    stmt = select(Transfer).order_by(Transfer.id.desc()).limit(limit)
    if before_id is not None:
        stmt = stmt.where(Transfer.id < before_id)
    if wallet_id is not None:
        stmt = stmt.where(
            or_(Transfer.from_wallet_id == wallet_id, Transfer.to_wallet_id == wallet_id)
        )
    return [svc.serialize_transfer(t) for t in db.scalars(stmt)]


@router.post("/api/transfers", dependencies=[Depends(require_app("transfers"))], status_code=201)
def create_transfer(
    body: TransferIn,
    request: Request,
    actor: User = Depends(require_permission("transfers.create")),
    db: DbSession = Depends(get_db),
):
    """Simulated: moves a tracked balance between two wallets. No real funds move."""
    try:
        svc.guard(note=body.note)
        amount = money.parse_amount(body.amount, allow_zero=False)
        symbol = svc.clean_symbol(body.symbol)
        # Hold the write lock from the balance check to the commit, so two transfers at the
        # same moment can't both spend the same coins.
        begin_immediate(db)
        src, dst = db.get(Wallet, body.from_wallet_id), db.get(Wallet, body.to_wallet_id)
        if src is None or dst is None:
            raise svc.WalletError(404, "Wallet not found.")
        record, warnings = svc.transfer(db, src, dst, symbol, amount, body.note.strip(), actor)
    except money.AmountError as e:
        return JSONResponse({"detail": str(e)}, status_code=422)
    except svc.WalletError as e:
        db.rollback()
        return JSONResponse({"detail": e.message, **e.extra}, status_code=e.status)
    write_audit(
        db,
        request,
        "transfer",
        user=actor,
        detail=f"#{record.id} {record.amount} {record.symbol} {src.name} -> {dst.name}"
        f" ({record.network or 'no network'}), simulated",
    )
    db.commit()
    return {**svc.serialize_transfer(record), "warnings": warnings}
