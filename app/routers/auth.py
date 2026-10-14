from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.audit import safe_username, write_audit
from app.db import get_db
from app.deps import (
    SESSION_COOKIE,
    current_session,
    effective_permissions,
    lookup_session,
    session_expiry,
)
from app.models import Session, User
from app.security import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    hash_token,
    new_token,
    verify_dummy,
    verify_password,
)
from app.timeutil import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID = "Invalid username or password"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


def _register_failure(db: DbSession, request: Request, user: User) -> None:
    """Count a failed password check; lock the account after too many in a row."""
    settings = request.app.state.settings
    user.failed_logins += 1
    if user.failed_logins >= settings.max_failed_logins:
        user.locked_until = utcnow() + timedelta(minutes=settings.lockout_minutes)
        user.failed_logins = 0
        write_audit(db, request, "login.lockout", user=user)


@router.post("/login")
def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession = Depends(get_db)
):
    settings = request.app.state.settings
    user = db.scalar(select(User).where(User.username == body.username))

    if user is None:
        verify_dummy(body.password)
        write_audit(
            db, request, "login.fail", username=safe_username(body.username), detail="unknown user"
        )
        db.commit()
        raise HTTPException(status_code=401, detail=INVALID)

    locked = user.locked_until is not None and user.locked_until > utcnow()
    if locked or not user.is_active:
        # Same answer as a wrong password, so callers can't tell locked/disabled/missing apart.
        verify_dummy(body.password)
        write_audit(
            db,
            request,
            "login.fail",
            user=user,
            detail="account locked" if locked else "account inactive",
        )
        db.commit()
        raise HTTPException(status_code=401, detail=INVALID)

    if not verify_password(user.password_hash, body.password):
        _register_failure(db, request, user)
        write_audit(db, request, "login.fail", user=user, detail="bad password")
        db.commit()
        raise HTTPException(status_code=401, detail=INVALID)

    user.failed_logins = 0
    user.locked_until = None
    token = new_token()
    db.add(
        Session(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=session_expiry(settings.session_hours),
        )
    )
    write_audit(db, request, "login.ok", user=user)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )
    return {"username": user.username}


@router.post("/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    found = lookup_session(db, request.cookies.get(SESSION_COOKIE))
    if found is not None:
        sess, user = found
        db.delete(sess)
        write_audit(db, request, "logout", user=user)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(found: tuple[Session, User] = Depends(current_session)):
    _, user = found
    return {
        "id": user.id,
        "username": user.username,
        "is_super": user.is_super,
        "permissions": sorted(effective_permissions(user)),
        "totp_enabled": user.totp_enabled,
        "preferences": user.preferences or {},
    }


@router.post("/password")
def change_password(
    body: PasswordChange,
    request: Request,
    found: tuple[Session, User] = Depends(current_session),
    db: DbSession = Depends(get_db),
):
    sess, user = found
    if not verify_password(user.password_hash, body.current_password):
        # Counts toward lockout so a stolen session can't be used to guess the password.
        _register_failure(db, request, user)
        write_audit(db, request, "password.fail", user=user, detail="bad current password")
        db.commit()
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.failed_logins = 0
    db.execute(delete(Session).where(Session.user_id == user.id, Session.id != sess.id))
    write_audit(db, request, "password.change", user=user, detail="other sessions revoked")
    db.commit()
    return {"ok": True}
