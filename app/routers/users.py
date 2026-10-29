from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import accounts, alerts, trading
from app.audit import write_audit
from app.db import get_db
from app.deps import effective_permissions, require_app, require_permission
from app.models import User
from app.permissions import (
    ALL_PERMISSIONS,
    PERMISSIONS,
    PRESETS,
    RESERVED_USERNAMES,
    SUPER_GRANTS_ONLY,
)
from app.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, hash_password
from app.timeutil import utcnow

router = APIRouter(tags=["users"])
manage = require_permission("users.manage")

USERNAME_PATTERN = r"^[a-z0-9_.-]{3,32}$"


def _check_permissions(value: list[str]) -> list[str]:
    unknown = set(value) - ALL_PERMISSIONS
    if unknown:
        raise ValueError(f"Unknown permissions: {', '.join(sorted(unknown))}")
    return sorted(set(value))


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    permissions: list[str] = Field(default_factory=list, max_length=len(PERMISSIONS))
    is_active: bool = True
    # Account rules (12a): pick their own password at first sign-in; must use 2FA.
    must_change_password: bool = False
    require_2fa: bool = False

    _perms = field_validator("permissions")(_check_permissions)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissions: list[str] | None = Field(default=None, max_length=len(PERMISSIONS))
    is_active: bool | None = None
    password: str | None = Field(
        default=None, min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH
    )
    must_change_password: bool | None = None
    require_2fa: bool | None = None

    @field_validator("permissions")
    @classmethod
    def _perms(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _check_permissions(value)


class UserOut(BaseModel):
    id: int
    username: str
    permissions: list[str]
    is_super: bool
    is_active: bool
    totp_enabled: bool
    locked: bool
    must_change_password: bool
    require_2fa: bool
    online: bool = False  # signed in with a desktop open right now
    live_cap: str | None = None  # None: the default cap
    live_cap_ceiling: str | None = None
    created_at: datetime


def user_out(user: User, online: bool = False) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        permissions=sorted(effective_permissions(user)),
        is_super=user.is_super,
        is_active=user.is_active,
        totp_enabled=user.totp_enabled,
        locked=user.locked_until is not None and user.locked_until > utcnow(),
        must_change_password=user.must_change_password,
        require_2fa=user.require_2fa or user.is_super,
        online=online,
        live_cap=user.live_cap,
        live_cap_ceiling=user.live_cap_ceiling,
        created_at=user.created_at,
    )


def _load_target(db: DbSession, actor: User, user_id: int) -> User:
    """Fetch a user the actor may modify, enforcing the no-escalation rules."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.is_super:
        raise HTTPException(status_code=403, detail="The super user cannot be changed")
    if target.id == actor.id:
        raise HTTPException(status_code=403, detail="You cannot change your own account here")
    if not effective_permissions(target) <= effective_permissions(actor):
        raise HTTPException(status_code=403, detail="That user has permissions you do not hold")
    return target


def _check_grant(actor: User, requested: list[str]) -> None:
    """`requested`: the permissions being added (all of them for a new user)."""
    reserved = set(requested) & SUPER_GRANTS_ONLY
    if reserved and not actor.is_super:
        raise HTTPException(
            status_code=403,
            detail=f"Only super can grant {', '.join(sorted(reserved))}",
        )
    missing = set(requested) - effective_permissions(actor)
    if missing:
        raise HTTPException(
            status_code=403,
            detail=f"You cannot grant permissions you do not hold: {', '.join(sorted(missing))}",
        )


@router.get("/api/meta/permissions", dependencies=[Depends(require_app("users"))])
def list_permissions(_: User = Depends(manage)):
    return {"permissions": PERMISSIONS, "presets": PRESETS}


@router.get(
    "/api/users", dependencies=[Depends(require_app("users"))], response_model=list[UserOut]
)
def list_users(request: Request, _: User = Depends(manage), db: DbSession = Depends(get_db)):
    online = set(request.app.state.hub.connected())
    return [user_out(u, u.id in online) for u in db.scalars(select(User).order_by(User.id))]


@router.post(
    "/api/users",
    dependencies=[Depends(require_app("users"))],
    status_code=201,
    response_model=UserOut,
)
def create_user(
    body: UserCreate,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    if body.username in RESERVED_USERNAMES:
        raise HTTPException(status_code=400, detail="That username is reserved")
    _check_grant(actor, body.permissions)
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        permissions=body.permissions,
        is_super=False,
        is_active=body.is_active,
        must_change_password=body.must_change_password,
        require_2fa=body.require_2fa,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists") from None
    write_audit(
        db,
        request,
        "user.create",
        user=actor,
        detail=f"{user.username} (id {user.id}) permissions={','.join(body.permissions) or '-'}"
        f" active={body.is_active}"
        + (" must_change_password" if body.must_change_password else "")
        + (" require_2fa" if body.require_2fa else ""),
    )
    db.commit()
    return user_out(user)


@router.patch(
    "/api/users/{user_id}", dependencies=[Depends(require_app("users"))], response_model=UserOut
)
def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    target = _load_target(db, actor, user_id)
    changes: list[str] = []
    revoke = False

    if body.permissions is not None:
        old = set(target.permissions or [])
        new = set(body.permissions)
        _check_grant(actor, sorted(new - old))
        if new != old:
            target.permissions = sorted(new)
            added, removed = sorted(new - old), sorted(old - new)
            changes.append(
                "permissions"
                + (f" +{','.join(added)}" if added else "")
                + (f" -{','.join(removed)}" if removed else "")
            )
    if body.is_active is not None and body.is_active != target.is_active:
        target.is_active = body.is_active
        changes.append(f"active={body.is_active}")
        revoke = revoke or not body.is_active
    if body.password is not None:
        accounts.set_password(target, body.password)
        changes.append("password reset")
        alerts.password_changed(db, request, target, by=actor.username)
        revoke = True

    # Rules apply from the account's next request: no need to sign it out.
    if body.must_change_password is not None and body.must_change_password != (
        target.must_change_password
    ):
        target.must_change_password = body.must_change_password
        changes.append(f"must_change_password={body.must_change_password}")
    if body.require_2fa is not None and body.require_2fa != target.require_2fa:
        target.require_2fa = body.require_2fa
        changes.append(f"require_2fa={body.require_2fa}")

    if revoke:
        accounts.revoke_sessions(db, target)
        changes.append("sessions revoked")
    if changes:
        write_audit(
            db,
            request,
            "user.update",
            user=actor,
            detail=f"{target.username} (id {target.id}): {'; '.join(changes)}",
        )
    db.commit()
    return user_out(target)


@router.delete(
    "/api/users/{user_id}", dependencies=[Depends(require_app("users"))], status_code=204
)
def delete_user(
    user_id: int,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    target = _load_target(db, actor, user_id)
    try:
        keys = trading.forget_user(db, target, f"its owner {target.username} was deleted")
    except trading.TradingError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    accounts.revoke_sessions(db, target)
    extra = f", {keys} trading key(s)" if keys else ""
    write_audit(
        db,
        request,
        "user.delete",
        user=actor,
        detail=f"{target.username} (id {target.id}{extra})",
    )
    db.delete(target)
    db.commit()


# ---- opening a window on someone's desktop (12b) --------------------------------------------

OPEN_PER_MINUTE = 10


class OpenWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    panel: str = Field(pattern=r"^[a-z]{2,20}$")


@router.post("/api/users/{user_id}/open-window", dependencies=[Depends(require_app("users"))])
def open_window(
    user_id: int,
    body: OpenWindow,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    """Open a window on a signed-in account's desktop (with a note saying who). Only windows
    that account may use; the same rules as changing the account (never super, never you)."""
    from collections import deque
    from time import monotonic

    from app import apps

    target = _load_target(db, actor, user_id)
    hub = request.app.state.hub
    if not target.is_active or target.id not in hub.connected():
        raise HTTPException(status_code=409, detail=f"{target.username} isn't signed in right now")
    usable = [*apps.CORE_APPS, *apps.usable_apps(target, apps.load_switches(db),
                                                 effective_permissions(target))]  # fmt: skip
    if body.panel not in usable:
        raise HTTPException(status_code=422, detail=f"{target.username} can't use that window")
    log = request.app.state.open_window_log.setdefault(target.id, deque())
    now = monotonic()
    while log and now - log[0] > 60:
        log.popleft()
    if len(log) >= OPEN_PER_MINUTE:
        raise HTTPException(status_code=429, detail="That's enough windows for a minute")
    log.append(now)
    write_audit(db, request, "user.open_window", user=actor,
                detail=f"{body.panel} for {target.username} (id {target.id})")  # fmt: skip
    db.commit()
    hub.publish(target.id, "open-window", {"panel": body.panel, "by": actor.username})
    return {"opened": body.panel, "for": target.username}


class TradingCaps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cap: str | None = Field(default=None, max_length=40)  # "" or None: the default
    ceiling: str | None = Field(default=None, max_length=40)  # "" or None: no ceiling
    code: str | None = Field(default=None, max_length=12)


@router.put("/api/users/{user_id}/trading", dependencies=[Depends(require_app("users"))])
def set_trading_caps(
    user_id: int,
    body: TradingCaps,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    """Someone's live-trading cap and ceiling (13a). Raising either needs the admin's own 2FA
    code; lowering doesn't (stopping is easy, starting deliberate)."""
    from app import trading as tr
    from app.routers.trading import require_code

    target = _load_target(db, actor, user_id)
    try:
        cap = tr.parse_cap(body.cap)
        ceiling = tr.parse_cap(body.ceiling, "The ceiling")
        old_cap, old_ceiling = tr.cap_of(target), tr.ceiling_of(target)
        new_cap = cap if cap is not None else tr.DEFAULT_CAP
        if cap is None and ceiling is not None:
            new_cap = min(new_cap, ceiling)  # the default comes down to the ceiling
        if tr.raises(old_cap, new_cap) or tr.raises(old_ceiling, ceiling):
            require_code(db, request, actor, body.code, "Raising a cap or ceiling")
        tr.set_caps(target, cap, ceiling)
    except tr.TradingError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    write_audit(
        db,
        request,
        "trading.cap",
        user=actor,
        detail=f"{target.username}: cap ${old_cap} -> ${tr.cap_of(target)}, ceiling "
        f"{old_ceiling or 'none'} -> {tr.ceiling_of(target) or 'none'}",
    )
    db.commit()
    return user_out(target)
