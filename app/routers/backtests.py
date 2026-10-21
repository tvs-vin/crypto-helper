"""The Backtester window (12c): run a plan over past prices, save runs, compare them. Needs
prices.view and the Backtester app; saved runs are each person's own. See app/backtest.py."""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import backtest as bt
from app.audit import write_audit
from app.db import get_db
from app.deps import require_app, require_permission
from app.models import BacktestRun, User
from app.prices.importer import PriceImport

router = APIRouter(
    prefix="/api/backtests", tags=["backtests"], dependencies=[Depends(require_app("backtest"))]
)
view = require_permission("prices.view")
MAX_SAVED = 50


def _params(raw: dict) -> bt.Params:
    try:
        return bt.Params(**raw)
    except ValidationError as e:
        msg = "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors())
        raise HTTPException(status_code=422, detail=msg) from None
    except TypeError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


def _run(db: DbSession, p: bt.Params) -> dict:
    try:
        return bt.run(db, p)
    except bt.NotEnoughData as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


def _brief(r: BacktestRun) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "text": bt.describe(r.params),
        "strategy": r.params["strategy"],
        "summary": r.summary,
        "created_at": r.created_at.isoformat(timespec="seconds"),
    }


@router.get("/meta")
def meta(_: User = Depends(view), db: DbSession = Depends(get_db)):
    """What can be tested: strategies, fee presets, and which coins have daily prices since when
    (per currency)."""
    cov = PriceImport.coverage(db)
    return {
        "strategies": bt.STRATEGIES,
        "fees": {k: {"name": n, "pct": p} for k, (n, p) in bt.FEES.items()},
        "coverage": {
            s: {
                q: {"first_day": v["first_day"], "days": v["days"]}
                for q, v in c.items()
                if v["days"]
            }
            for s, c in cov.items()
        },
        "max_years": bt.MAX_YEARS,
    }


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    params: dict


@router.post("/run")
def run(body: RunIn, _: User = Depends(view), db: DbSession = Depends(get_db)):
    """Run without saving (nothing changes)."""
    p = _params(body.params)
    return {"params": p.model_dump(mode="json"), "text": bt.describe(p.model_dump(mode="json")),
            **_run(db, p)}  # fmt: skip


class SaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    params: dict


@router.get("")
def list_runs(me: User = Depends(view), db: DbSession = Depends(get_db)):
    rows = db.scalars(
        select(BacktestRun).where(BacktestRun.user_id == me.id).order_by(BacktestRun.id.desc())
    ).all()
    return {"runs": [_brief(r) for r in rows], "max": MAX_SAVED}


@router.post("", status_code=201)
def save(body: SaveIn, request: Request, me: User = Depends(view), db: DbSession = Depends(get_db)):
    p = _params(body.params)
    count = db.scalar(
        select(func.count()).select_from(BacktestRun).where(BacktestRun.user_id == me.id)
    )
    if (count or 0) >= MAX_SAVED:
        raise HTTPException(status_code=409, detail=f"At most {MAX_SAVED} saved runs: delete one")
    from app.wallets import WalletError, guard

    name = body.name.strip()
    try:
        guard(name=name)  # free text: never a pasted seed phrase or key
    except WalletError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    result = _run(db, p)
    params = p.model_dump(mode="json")
    r = BacktestRun(user_id=me.id, name=name, params=params, summary=result["summary"],
                    series=result["series"], trades=result["trades"])  # fmt: skip
    db.add(r)
    db.flush()
    write_audit(db, request, "backtest.save", user=me, detail=f"{name}: {bt.describe(params)}")
    db.commit()
    return {**_brief(r), "series": r.series, "trades": r.trades[:200]}


def _mine(db: DbSession, me: User, run_id: int) -> BacktestRun:
    r = db.get(BacktestRun, run_id)
    if r is None or r.user_id != me.id:
        raise HTTPException(status_code=404, detail="No such saved run")
    return r


@router.get("/{run_id}")
def get_run(run_id: int, me: User = Depends(view), db: DbSession = Depends(get_db)):
    r = _mine(db, me, run_id)
    return {**_brief(r), "params": r.params, "series": r.series, "trades": r.trades[:200],
            "trades_total": len(r.trades)}  # fmt: skip


@router.get("/{run_id}/trades.csv")
def trades_csv(run_id: int, me: User = Depends(view), db: DbSession = Depends(get_db)):
    r = _mine(db, me, run_id)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["day", "side", "symbol", "units", "price", "value", "fee", "currency"])
    for t in r.trades:
        w.writerow([t["day"], t["side"], t["symbol"], t["units"], t["price"], t["value"], t["fee"],
                    r.params["currency"].upper()])  # fmt: skip
    safe = "".join(c if c.isalnum() else "-" for c in r.name)[:40] or "backtest"
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="backtest-{safe}.csv"'},
    )


@router.delete("/{run_id}", status_code=204)
def delete_run(
    run_id: int, request: Request, me: User = Depends(view), db: DbSession = Depends(get_db)
):
    r = _mine(db, me, run_id)
    write_audit(db, request, "backtest.delete", user=me, detail=r.name)
    db.delete(r)
    db.commit()
