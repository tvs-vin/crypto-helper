from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import accounts
from app.audit import write_audit
from app.db import get_db
from app.deps import effective_permissions, require_permission
from app.models import User
from app.permissions import ALL_PERMISSIONS, PERMISSIONS, PRESETS, RESERVED_USERNAMES
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

    _perms = field_validator("permissions")(_check_permissions)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissions: list[str] | None = Field(default=None, max_length=len(PERMISSIONS))
    is_active: bool | None = None
    password: str | None = Field(
        default=None, min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH
    )

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
    created_at: datetime


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        permissions=sorted(effective_permissions(user)),
        is_super=user.is_super,
        is_active=user.is_active,
        totp_enabled=user.totp_enabled,
        locked=user.locked_until is not None and user.locked_until > utcnow(),
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
    missing = set(requested) - effective_permissions(actor)
    if missing:
        raise HTTPException(
            status_code=403,
            detail=f"You cannot grant permissions you do not hold: {', '.join(sorted(missing))}",
        )


@router.get("/api/meta/permissions")
def list_permissions(_: User = Depends(manage)):
    return {"permissions": PERMISSIONS, "presets": PRESETS}


@router.get("/api/users", response_model=list[UserOut])
def list_users(_: User = Depends(manage), db: DbSession = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/api/users", status_code=201, response_model=UserOut)
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
        f" active={body.is_active}",
    )
    db.commit()
    return user_out(user)


@router.patch("/api/users/{user_id}", response_model=UserOut)
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
        revoke = True

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


@router.delete("/api/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    target = _load_target(db, actor, user_id)
    accounts.revoke_sessions(db, target)
    write_audit(
        db, request, "user.delete", user=actor, detail=f"{target.username} (id {target.id})"
    )
    db.delete(target)
    db.commit()
