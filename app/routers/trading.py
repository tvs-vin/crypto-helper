"""Live trading (phase 4, 13a): trading keys and caps. The window is the Live trading app.

Every key is checked with the exchange before it's saved (no database lock meanwhile): one
that can withdraw is refused. Adding keys and raising caps need 2FA turned on; raising a cap
needs a fresh 2FA code. Everything that changes is audited; credentials never leave encrypted.
See app/trading.py for the rules.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import readiness
from app import trading as tr
from app.audit import write_audit
from app.db import begin_immediate, get_db
from app.deps import current_user, effective_permissions, require_app, require_permission
from app.models import TradingKey, User
from app.secret_guard import find_secret
from app.sync import SourceError, available
from app.timeutil import utcnow

router = APIRouter(prefix="/api/trading", tags=["trading"])
in_app = [Depends(require_app("trading"))]
ANCHORS = {"demo": "demo-exchange"}  # the guide's headings (kramdown ids)
NEED_2FA = "Turn on two-factor login first (Settings → Account): live trading moves real money"


def _fail(e: tr.TradingError):
    detail = {"message": e.message, **e.extra} if e.extra else e.message
    raise HTTPException(status_code=e.status, detail=detail) from None


def _any_live(user: User = Depends(current_user)) -> User:
    if not effective_permissions(user) & {"live.trade", "live.keys.shared", "live.cap"}:
        raise HTTPException(status_code=403, detail="You don't have live trading permissions")
    return user


def require_code(db: DbSession, request: Request, user: User, code: str | None, what: str):
    """A fresh 2FA code from the authenticator app (not a recovery code), never reused."""
    from app import totp
    from app.routers.auth import _decrypt_secret, _register_failure

    if not user.totp_enabled:
        raise HTTPException(status_code=403, detail=NEED_2FA)
    secret = _decrypt_secret(request, user) if code and totp.looks_like_totp(code) else None
    step = totp.verify_totp(secret, code, user.totp_last_step) if secret else None
    if step is None:
        _register_failure(db, request, user)
        write_audit(db, request, "trading.fail", user=user, detail=f"bad 2FA code: {what}")
        db.commit()
        raise HTTPException(status_code=403, detail=f"{what} needs a current 2FA code")
    user.totp_last_step = step


def _key_out(request: Request, db: DbSession, k: TradingKey) -> dict:
    ex = available(request.app.state.settings).get(k.kind)
    owner = db.get(User, k.owner_id) if k.owner_id else None
    return {
        "id": k.id,
        "kind": k.kind,
        "exchange": ex.name if ex else k.kind,
        "label": k.label,
        "masked": k.masked,
        "shared": k.owner_id is None,
        "owner": owner.username if owner else None,
        "check": tr.describe(k.check or {}),
        "ip_locked": (k.check or {}).get("ip_locked"),
        "checked_at": k.checked_at.isoformat(timespec="seconds") if k.checked_at else None,
        "exchange_on": tr.enabled(db, k.kind),
        "created_by": k.created_by,
        "created_at": k.created_at.isoformat(timespec="seconds"),
    }


@router.get("", dependencies=in_app)
def overview(request: Request, me: User = Depends(_any_live), db: DbSession = Depends(get_db)):
    """Everything the Live trading window shows: exchanges switched on, your cap, your keys,
    and whether live trading may be switched on at all (readiness)."""
    perms = effective_permissions(me)
    on = tr.switches(db)
    ready = readiness.report(db, test=request.app.state.readiness_test_clock)
    return {
        "exchanges": [
            {
                "id": e.id,
                "name": e.name,
                "on": bool(on.get(e.id)),
                "guide": "guides/live-trading#" + ANCHORS.get(e.id, e.id),
                "trading_confirm_text": e.trading_confirm_text,
                "fields": [
                    {
                        "name": f.name,
                        "label": f.label,
                        "secret": f.secret,
                        "help": f.help,
                        "multiline": f.multiline,
                    }  # fmt: skip
                    for f in e.fields
                ],
            }
            for e in available(request.app.state.settings).values()
        ],
        "caps": tr.caps_out(me),
        "keys": [_key_out(request, db, k) for k in tr.visible_keys(db, me)],
        "may": {
            "trade": "live.trade" in perms,
            "shared_keys": "live.keys.shared" in perms,
            "change_cap": "live.cap" in perms,
            "two_factor": me.totp_enabled,
        },
        "live_allowed": ready["live_allowed"],
    }


class NewKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=16)
    label: str = Field(min_length=1, max_length=64)
    credentials: dict[str, str] = Field(max_length=8)
    shared: bool = False
    confirm_no_withdrawals: bool = False


@router.post("/keys", status_code=201, dependencies=in_app)
def add_key(body: NewKey, request: Request, me: User = Depends(_any_live), db=Depends(get_db)):
    perms = effective_permissions(me)
    needed = "live.keys.shared" if body.shared else "live.trade"
    if needed not in perms:
        raise HTTPException(status_code=403, detail=f"Adding this key needs {needed}")
    if not me.totp_enabled:
        raise HTTPException(status_code=403, detail=NEED_2FA)
    exchange = available(request.app.state.settings).get(body.kind)
    if exchange is None:
        raise HTTPException(status_code=422, detail="That exchange isn't available here")
    if not tr.enabled(db, exchange.id):
        raise HTTPException(
            status_code=409, detail=f"Live trading on {exchange.name} isn't switched on (super)"
        )
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
    try:
        check = exchange.check_trading(creds)
        stored = tr.verdict(check, body.confirm_no_withdrawals, me.username, exchange)
    except SourceError as e:
        raise HTTPException(422, f"{exchange.name} didn't accept it: {e}") from None
    except tr.TradingError as e:
        _fail(e)
    begin_immediate(db)
    k = TradingKey(
        kind=exchange.id,
        label=label,
        owner_id=None if body.shared else me.id,
        secret_encrypted=request.app.state.secret_box.encrypt(json.dumps(creds)),
        masked=exchange.mask(creds),
        check=stored,
        checked_at=utcnow(),
        created_by=me.username,
    )
    db.add(k)
    db.flush()
    kind = "shared" if body.shared else "personal"
    detail = f"{kind} {exchange.name}: {label} ({k.masked}); {tr.describe(stored)}"
    write_audit(db, request, "trading.key.add", user=me, detail=detail)
    db.commit()
    return _key_out(request, db, k)


def _visible(db: DbSession, me: User, key_id: int) -> TradingKey:
    k = db.get(TradingKey, key_id)
    if k is None or not tr.may_see(me, k):
        raise HTTPException(status_code=404, detail="No such trading key")
    return k


@router.post("/keys/{key_id}/check", dependencies=in_app)
def recheck_key(key_id: int, request: Request, me: User = Depends(_any_live), db=Depends(get_db)):
    """Ask the exchange again. A key that can now withdraw is deleted at once."""
    k = _visible(db, me, key_id)
    exchange = available(request.app.state.settings).get(k.kind)
    if exchange is None:
        raise HTTPException(status_code=409, detail="That exchange isn't available here")
    creds = json.loads(request.app.state.secret_box.decrypt(k.secret_encrypted))
    previously_confirmed = (k.check or {}).get("confirmed_by")
    db.commit()
    try:
        check = exchange.check_trading(creds)
        stored = tr.verdict(check, bool(previously_confirmed), previously_confirmed or "", exchange)
    except SourceError as e:
        raise HTTPException(422, f"{exchange.name} didn't accept it: {e}") from None
    except tr.TradingError as e:
        begin_immediate(db)
        k = db.get(TradingKey, key_id)
        if k is not None and e.status == 422 and "withdraw" in e.message:
            write_audit(db, request, "trading.key.delete", user=me,
                        detail=f"{k.label} ({k.masked}): it can now withdraw")  # fmt: skip
            db.delete(k)
        db.commit()
        _fail(e)
    begin_immediate(db)
    k = db.get(TradingKey, key_id)
    k.check, k.checked_at = stored, utcnow()
    detail = f"{k.label}: {tr.describe(stored)}"
    write_audit(db, request, "trading.key.check", user=me, detail=detail)
    db.commit()
    return _key_out(request, db, k)


@router.delete("/keys/{key_id}", status_code=204, dependencies=in_app)
def delete_key(key_id: int, request: Request, me: User = Depends(_any_live), db=Depends(get_db)):
    k = _visible(db, me, key_id)
    write_audit(db, request, "trading.key.delete", user=me, detail=f"{k.label} ({k.masked})")
    db.delete(k)
    db.commit()


class CapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cap: str = Field(max_length=40)
    code: str | None = Field(default=None, max_length=12)


@router.put("/me/cap", dependencies=in_app)
def set_my_cap(
    body: CapIn,
    request: Request,
    me: User = Depends(require_permission("live.cap")),
    db: DbSession = Depends(get_db),
):
    try:
        cap = tr.parse_cap(body.cap)
        if cap is None:
            raise tr.TradingError(422, "Give an amount")
        if tr.raises(tr.cap_of(me), cap):
            require_code(db, request, me, body.code, "Raising your cap")
        old = tr.set_own_cap(me, cap)
    except tr.TradingError as e:
        _fail(e)
    write_audit(db, request, "trading.cap", user=me, detail=f"own cap ${old} -> ${cap}")
    db.commit()
    return tr.caps_out(me)


# ---- admins: everyone's keys -----------------------------------------------------------------


@router.get("/keys/all", dependencies=[Depends(require_app("users"))])
def all_keys(
    request: Request,
    _: User = Depends(require_permission("users.manage")),
    db: DbSession = Depends(get_db),
):
    """Every trading key on the install, masked (admins can delete them from Users)."""
    keys = db.scalars(select(TradingKey).order_by(TradingKey.id))
    return [_key_out(request, db, k) for k in keys]


@router.delete(
    "/keys/{key_id}/admin", status_code=204, dependencies=[Depends(require_app("users"))]
)
def admin_delete_key(
    key_id: int,
    request: Request,
    me: User = Depends(require_permission("users.manage")),
    db: DbSession = Depends(get_db),
):
    """An admin removes someone's trading key (a person they may manage, or a shared key if
    they may use shared keys themselves; super: any)."""
    k = db.get(TradingKey, key_id)
    if k is None:
        raise HTTPException(status_code=404, detail="No such trading key")
    if not me.is_super:
        if k.owner_id is None:
            if "live.keys.shared" not in effective_permissions(me):
                raise HTTPException(status_code=403, detail="Shared keys need live.keys.shared")
        else:
            from app.routers.users import _load_target

            _load_target(db, me, k.owner_id)  # the usual rules for managing that account
    detail = f"{k.label} ({k.masked}) by an admin"
    write_audit(db, request, "trading.key.delete", user=me, detail=detail)
    db.delete(k)
    db.commit()
