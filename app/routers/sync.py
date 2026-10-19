"""Connections (read-only exchange keys), linking wallets to them, and syncing (phase 2).

Managing connections needs `wallets.connect`. A key is checked before it's saved: one that can
trade or move funds is refused; where the exchange can't say, the owner has to confirm. Every
check talks to the exchange, so the database lock is never held meanwhile.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import networks as nets
from app.audit import write_audit
from app.db import begin_immediate, get_db
from app.deps import require_app, require_permission
from app.models import Connection, User, Wallet, WalletSource
from app.secret_guard import find_secret
from app.sync import SourceError, available, chains, engine
from app.timeutil import utcnow

router = APIRouter(tags=["sync"], dependencies=[Depends(require_app("wallets"))])
connect = require_permission("wallets.connect")
edit = require_permission("wallets.edit")


def _exchange(request: Request, kind: str):
    found = available(request.app.state.settings).get(kind)
    if found is None:
        raise HTTPException(status_code=422, detail="That exchange isn't available here")
    return found


def _out(request: Request, c: Connection, db: DbSession) -> dict:
    ex = available(request.app.state.settings).get(c.kind)
    used = db.execute(
        select(Wallet.id, Wallet.name)
        .join(WalletSource, WalletSource.wallet_id == Wallet.id)
        .where(WalletSource.connection_id == c.id)
    ).all()
    return {
        "id": c.id,
        "kind": c.kind,
        "exchange": ex.name if ex else c.kind,
        "label": c.label,
        "masked": c.masked,
        "check_summary": c.check_summary,
        "checked_at": c.checked_at,
        "created_by": c.created_by,
        "created_at": c.created_at,
        "wallets": [{"id": i, "name": n} for i, n in used],
    }


def _check(exchange, creds: dict, confirmed: bool, who: str) -> str:
    """The permission check. Returns the summary to store, or refuses."""
    try:
        result = exchange.check(creds)
    except SourceError as e:
        raise HTTPException(
            status_code=422, detail=f"{exchange.name} didn't accept it: {e}"
        ) from None
    if result.read_only is False:
        raise HTTPException(status_code=422, detail=engine.refused_message(exchange))
    if result.read_only is None:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"{result.summary}. Check the key's permissions on "
                    f"{exchange.name} and confirm.",
                    "confirm": exchange.confirm_text,
                },
            )
        return f"Unknown to the app ({result.summary}); confirmed view-only by {who}"
    return result.summary


# ---- what's available ----------------------------------------------------------------------


@router.get("/api/sync/exchanges")
def exchanges(request: Request, _: User = Depends(connect)):
    return [
        {
            "id": e.id,
            "name": e.name,
            "guide": e.guide,
            "confirm_text": e.confirm_text,
            "fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "secret": f.secret,
                    "help": f.help,
                    "multiline": f.multiline,
                }
                for f in e.fields
            ],
        }
        for e in available(request.app.state.settings).values()
    ]


# ---- connections ---------------------------------------------------------------------------


@router.get("/api/connections")
def list_connections(request: Request, _: User = Depends(connect), db: DbSession = Depends(get_db)):
    rows = db.scalars(select(Connection).order_by(Connection.id)).all()
    return [_out(request, c, db) for c in rows]


class NewConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=16)
    label: str = Field(min_length=1, max_length=64)
    credentials: dict[str, str] = Field(max_length=8)
    confirm_read_only: bool = False


@router.post("/api/connections", status_code=201)
def add_connection(
    body: NewConnection,
    request: Request,
    me: User = Depends(connect),
    db: DbSession = Depends(get_db),
):
    exchange = _exchange(request, body.kind)
    names = {f.name for f in exchange.fields}
    if set(body.credentials) != names or any(len(v) > 4000 for v in body.credentials.values()):
        raise HTTPException(
            status_code=422,
            detail=f"{exchange.name} needs: " + ", ".join(f.label for f in exchange.fields),
        )
    creds = {k: v.strip() for k, v in body.credentials.items()}
    if not all(creds.values()):
        raise HTTPException(status_code=422, detail="Fill in every field")
    label = body.label.strip()
    if find_secret(label):
        raise HTTPException(status_code=422, detail="Give it a plain name.")
    db.commit()  # no lock while the exchange answers
    summary = _check(exchange, creds, body.confirm_read_only, me.username)
    begin_immediate(db)
    c = Connection(
        kind=exchange.id,
        label=label,
        masked=exchange.mask(creds),
        check_summary=summary,
        checked_at=utcnow(),
        created_by=me.username,
        secret_encrypted=request.app.state.secret_box.encrypt(json.dumps(creds)),
    )
    db.add(c)
    db.flush()
    write_audit(
        db,
        request,
        "connection.add",
        user=me,
        detail=f"{exchange.name}: {label} ({c.masked}); {summary}",
    )
    db.commit()
    return _out(request, c, db)


def _get(db: DbSession, connection_id: int) -> Connection:
    c = db.get(Connection, connection_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return c


class Rename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=64)


@router.patch("/api/connections/{connection_id}")
def rename_connection(
    connection_id: int,
    body: Rename,
    request: Request,
    me: User = Depends(connect),
    db: DbSession = Depends(get_db),
):
    c = _get(db, connection_id)
    label = body.label.strip()
    if find_secret(label):
        raise HTTPException(status_code=422, detail="Give it a plain name.")
    write_audit(db, request, "connection.rename", user=me, detail=f"{c.label} -> {label}")
    c.label = label
    db.commit()
    return _out(request, c, db)


@router.post("/api/connections/{connection_id}/check")
def check_connection(
    connection_id: int,
    request: Request,
    me: User = Depends(connect),
    db: DbSession = Depends(get_db),
):
    """Ask the exchange again (e.g. after changing the key's permissions there)."""
    c = _get(db, connection_id)
    exchange = _exchange(request, c.kind)
    creds = engine.credentials(request.app.state.secret_box, c)
    previously_unknown = c.check_summary.startswith("Unknown")
    db.commit()
    try:
        summary = _check(exchange, creds, previously_unknown, me.username)
        outcome = summary
    except HTTPException as e:
        outcome = f"refused: {e.detail if isinstance(e.detail, str) else e.detail['message']}"
        begin_immediate(db)
        write_audit(db, request, "connection.check", user=me, detail=f"{c.label}: {outcome}")
        db.commit()
        raise
    begin_immediate(db)
    c = _get(db, connection_id)
    c.check_summary, c.checked_at = summary, utcnow()
    write_audit(db, request, "connection.check", user=me, detail=f"{c.label}: {outcome}")
    db.commit()
    return _out(request, c, db)


@router.delete("/api/connections/{connection_id}", status_code=204)
def delete_connection(
    connection_id: int,
    request: Request,
    me: User = Depends(connect),
    db: DbSession = Depends(get_db),
):
    c = _get(db, connection_id)
    used = db.scalars(select(WalletSource).where(WalletSource.connection_id == c.id)).all()
    if used:
        raise HTTPException(
            status_code=409,
            detail=f"{len(used)} wallet(s) sync from it: switch them to manual first",
        )
    write_audit(db, request, "connection.delete", user=me, detail=f"{c.label} ({c.masked})")
    db.delete(c)
    db.commit()


# ---- a wallet's source, and syncing ----------------------------------------------------------


def source_out(db: DbSession, request: Request, wallet_id: int) -> dict | None:
    s = db.get(WalletSource, wallet_id)
    if s is None:
        return None
    conn = db.get(Connection, s.connection_id) if s.connection_id else None
    ex = available(request.app.state.settings).get(conn.kind) if conn else None
    return {
        "kind": s.kind,
        "connection_id": s.connection_id,
        "label": f"{ex.name if ex else conn.kind}: {conn.label}" if conn else s.watch_masked,
        "info": (s.options or {}).get("info") or {},
        "last_ok_at": s.last_ok_at,
        "last_try_at": s.last_try_at,
        "last_error": s.last_error,
        "failures": s.failures,
        "untracked": s.untracked,
    }


class SourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=r"^(manual|exchange|onchain)$")
    connection_id: int | None = None
    # On-chain: addresses (default: the wallet's own), or a Bitcoin xpub and its address type.
    addresses: list[str] = Field(default_factory=list, max_length=chains.MAX_ADDRESSES)
    xpub: str | None = Field(default=None, max_length=200)
    script: str = Field(default="auto", max_length=8)


@router.put("/api/wallets/{wallet_id}/source")
def set_source(
    wallet_id: int,
    body: SourceIn,
    request: Request,
    me: User = Depends(connect),
    db: DbSession = Depends(get_db),
):
    from app.deps import effective_permissions

    if "wallets.edit" not in effective_permissions(me):
        raise HTTPException(status_code=403, detail="Permission denied")
    wallet = db.get(Wallet, wallet_id)
    if wallet is None:
        raise HTTPException(status_code=404, detail="Wallet not found")
    current = db.get(WalletSource, wallet_id)
    if body.kind == "manual":
        if current is not None:
            db.delete(current)
            write_audit(
                db,
                request,
                "wallet.source",
                user=me,
                detail=f"{wallet.name} (id {wallet.id}): manual",
            )
        db.commit()
        return {"sync": None}
    if body.kind == "onchain":
        if wallet.kind != "onchain":
            raise HTTPException(status_code=422, detail="Only on-chain wallets sync from addresses")
        if (
            body.xpub
            and find_secret(body.xpub)
            and not body.xpub.strip().startswith(tuple(chains.XPUB_PREFIXES))
        ):
            raise HTTPException(status_code=422, detail=chains.PRIVATE_KEY_WARNING)
        addresses = body.addresses or ([wallet.address] if wallet.address else [])
        try:
            watch = chains.check_watch(wallet.network or "", addresses, body.xpub, body.script)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        conn, label = None, f"{nets.network_name(wallet.network)} {watch.masked()}"
    else:
        if wallet.kind != "exchange":
            raise HTTPException(
                status_code=422, detail="Only exchange wallets sync from an exchange"
            )
        conn = db.get(Connection, body.connection_id) if body.connection_id else None
        if conn is None:
            raise HTTPException(status_code=422, detail="Choose a connection")
        watch, label = None, f"{conn.label} ({conn.kind})"
    if current is None:
        current = WalletSource(wallet_id=wallet.id, kind=body.kind, options={}, untracked=[])
        db.add(current)
    current.kind, current.connection_id = body.kind, conn.id if conn else None
    box = request.app.state.secret_box
    current.watch_encrypted = box.encrypt(watch.dump()) if watch else None
    current.watch_masked = label if watch else None
    current.last_try_at = current.last_ok_at = current.last_error = None
    current.failures, current.untracked, current.options = 0, [], {}
    write_audit(
        db, request, "wallet.source", user=me, detail=f"{wallet.name} (id {wallet.id}): {label}"
    )
    db.commit()
    return {"sync": source_out(db, request, wallet_id)}


@router.post("/api/wallets/{wallet_id}/sync")
def sync_now(
    wallet_id: int, request: Request, me: User = Depends(edit), db: DbSession = Depends(get_db)
):
    if db.get(WalletSource, wallet_id) is None:
        raise HTTPException(
            status_code=409, detail="This wallet isn't synced (its balances are typed in)"
        )
    db.commit()  # syncing talks to the exchange: no lock meanwhile
    result = engine.sync_wallet(request.app.state, wallet_id, actor=me)
    db.expire_all()
    return {
        "ok": result.ok,
        "changes": result.changes,
        "error": result.error,
        "sync": source_out(db, request, wallet_id),
    }


@router.get("/api/sync/settings")
def get_settings(_: User = Depends(connect), db: DbSession = Depends(get_db)):
    return engine.load_settings(db).model_dump()


@router.put("/api/sync/settings")
def put_settings(
    body: engine.SyncSettings,
    request: Request,
    me: User = Depends(connect),
    db: DbSession = Depends(get_db),
):
    engine.save_settings(db, body, me.username)
    write_audit(
        db,
        request,
        "sync.settings",
        user=me,
        detail=f"{'on' if body.enabled else 'off'}, every {body.interval_minutes} min",
    )
    db.commit()
    return body.model_dump()


@router.get("/api/sync/chains")
def get_chains(_: User = Depends(connect), db: DbSession = Depends(get_db)):
    s = chains.load_settings(db)
    return {
        **s.model_dump(),
        "defaults": {"esplora_url": chains.DEFAULT_ESPLORA, "rpc": chains.DEFAULT_RPC},
    }


@router.put("/api/sync/chains")
def put_chains(
    body: chains.ChainSettings,
    request: Request,
    me: User = Depends(connect),
    db: DbSession = Depends(get_db),
):
    chains.save_settings(db, body, me.username)
    own = [n for n in body.rpc] + (
        ["bitcoin"] if body.esplora_url != chains.DEFAULT_ESPLORA else []
    )
    write_audit(
        db,
        request,
        "sync.chains",
        user=me,
        detail="own data servers for: " + (", ".join(own) or "none"),
    )
    db.commit()
    return body.model_dump()
