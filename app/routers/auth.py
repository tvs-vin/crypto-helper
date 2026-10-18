import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import accounts, alerts, apps, totp
from app.audit import client_ip, safe_username, write_audit
from app.crypto import InvalidToken
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
    hash_token,
    new_token,
    verify_dummy,
    verify_password,
)
from app.timeutil import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger(__name__)

INVALID = "Invalid username or password"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    # 6-digit authenticator code, or a recovery code, once 2FA is enabled.
    totp: str | None = Field(default=None, max_length=32)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class CodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class PasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class EnableBody(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    # Asked again: a stolen session alone must not be enough to put someone else's
    # authenticator on the account (that would lock its owner out).
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


def _register_failure(db: DbSession, request: Request, user: User) -> None:
    """Count a failed password or 2FA check; lock the account after too many in a row."""
    settings = request.app.state.settings
    user.failed_logins += 1
    if user.failed_logins >= settings.max_failed_logins:
        user.locked_until = utcnow() + timedelta(minutes=settings.lockout_minutes)
        user.failed_logins = 0
        write_audit(db, request, "login.lockout", user=user)
        alerts.locked_out(db, request, user, settings.max_failed_logins, settings.lockout_minutes)


def _decrypt_secret(request: Request, user: User) -> str | None:
    try:
        return request.app.state.secret_box.decrypt(user.totp_secret)
    except InvalidToken:
        log.error("2FA secret for user id %s can't be decrypted: wrong secret key?", user.id)
        return None


def _check_second_factor(db: DbSession, request: Request, user: User, code: str) -> bool:
    """Verify an authenticator code or consume a recovery code."""
    if totp.looks_like_totp(code):
        secret = _decrypt_secret(request, user)
        step = totp.verify_totp(secret, code, user.totp_last_step) if secret else None
        if step is None:
            return False
        user.totp_last_step = step
        return True
    if accounts.use_recovery_code(db, user, code):
        left = accounts.recovery_codes_left(db, user)  # autoflush: the used one is gone
        write_audit(db, request, "2fa.recovery_used", user=user, detail=f"{left} codes left")
        alerts.recovery_code_used(db, request, user, left)
        return True
    return False


def _verify_password_or_fail(
    db: DbSession, request: Request, user: User, password: str, action: str
) -> None:
    """Re-check the password for a sensitive action; failures count toward lockout."""
    if not verify_password(user.password_hash, password):
        _register_failure(db, request, user)
        write_audit(db, request, action, user=user, detail="bad password")
        db.commit()
        raise HTTPException(status_code=403, detail="Password is incorrect")


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

    if user.totp_enabled:
        if not body.totp:
            # Normal two-step flow: the UI now shows the code box. Not counted as a failure.
            return JSONResponse(
                {"detail": "2FA code required", "totp_required": True}, status_code=401
            )
        if not _check_second_factor(db, request, user, body.totp):
            _register_failure(db, request, user)
            write_audit(db, request, "login.fail", user=user, detail="bad 2FA code")
            db.commit()
            return JSONResponse(
                {"detail": "Invalid 2FA code", "totp_required": True}, status_code=401
            )

    accounts.unlock(user)
    agent = clean_agent(request.headers.get("user-agent"))
    device = describe_agent(agent)
    alerts.signed_in(db, request, user, device)  # before this sign-in is recorded
    token = new_token()
    db.add(
        Session(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=session_expiry(settings.session_hours),
            source_ip=client_ip(request),
            user_agent=agent,
        )
    )
    write_audit(db, request, "login.ok", user=user, detail=device)
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
    return {
        "username": user.username,
        # The spec asks to offer 2FA enrolment to `super` at first login.
        "totp_setup_recommended": user.is_super and not user.totp_enabled,
    }


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
def me(found: tuple[Session, User] = Depends(current_session), db: DbSession = Depends(get_db)):
    _, user = found
    perms = effective_permissions(user)
    return {
        "id": user.id,
        "username": user.username,
        "is_super": user.is_super,
        "permissions": sorted(perms),
        # Windows this account may open (the server checks each request again).
        "apps": [*apps.CORE_APPS, *apps.usable_apps(user, apps.load_switches(db), perms)],
        "totp_enabled": user.totp_enabled,
        "recovery_codes_left": accounts.recovery_codes_left(db, user) if user.totp_enabled else 0,
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
    accounts.set_password(user, body.new_password)
    accounts.revoke_sessions(db, user, keep_session_id=sess.id)
    write_audit(db, request, "password.change", user=user, detail="other sessions revoked")
    alerts.password_changed(db, request, user)
    db.commit()
    return {"ok": True}


# ---- 2FA ---------------------------------------------------------------------------------


@router.post("/totp/setup")
def totp_setup(
    request: Request,
    found: tuple[Session, User] = Depends(current_session),
    db: DbSession = Depends(get_db),
):
    """Start enrolment: a new secret is stored (encrypted) but 2FA isn't on until /enable."""
    _, user = found
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="2FA is already enabled")
    secret = totp.new_secret()
    user.totp_secret = request.app.state.secret_box.encrypt(secret)
    user.totp_last_step = None
    write_audit(db, request, "2fa.setup", user=user)
    db.commit()
    uri = totp.provisioning_uri(secret, user.username)
    return {"secret": secret, "otpauth_uri": uri, "qr": totp.qr_data_uri(uri)}


@router.post("/totp/enable")
def totp_enable(
    body: EnableBody,
    request: Request,
    found: tuple[Session, User] = Depends(current_session),
    db: DbSession = Depends(get_db),
):
    sess, user = found
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="2FA is already enabled")
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Start with /api/auth/totp/setup")
    _verify_password_or_fail(db, request, user, body.password, "2fa.enable.fail")
    secret = _decrypt_secret(request, user)
    step = totp.verify_totp(secret, body.code, None) if secret else None
    if step is None:
        raise HTTPException(
            status_code=400,
            detail="That code doesn't match. Check the time on your phone and try the newest code.",
        )
    user.totp_enabled = True
    user.totp_last_step = step
    codes = accounts.issue_recovery_codes(db, user)
    revoked = accounts.revoke_sessions(db, user, keep_session_id=sess.id)
    write_audit(
        db,
        request,
        "2fa.enable",
        user=user,
        detail=f"{len(codes)} recovery codes issued; {revoked} other sessions revoked",
    )
    db.commit()
    return {"recovery_codes": codes}


@router.post("/totp/disable")
def totp_disable(
    body: PasswordBody,
    request: Request,
    found: tuple[Session, User] = Depends(current_session),
    db: DbSession = Depends(get_db),
):
    _, user = found
    if not user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    _verify_password_or_fail(db, request, user, body.password, "2fa.disable.fail")
    accounts.reset_2fa(db, user)
    write_audit(db, request, "2fa.disable", user=user)
    alerts.twofa_off(db, request, user)
    db.commit()
    return {"ok": True}


@router.post("/totp/recovery-codes")
def totp_new_recovery_codes(
    body: PasswordBody,
    request: Request,
    found: tuple[Session, User] = Depends(current_session),
    db: DbSession = Depends(get_db),
):
    """Replace all recovery codes with a fresh set (the old ones stop working)."""
    _, user = found
    if not user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    _verify_password_or_fail(db, request, user, body.password, "2fa.recovery.fail")
    codes = accounts.issue_recovery_codes(db, user)
    write_audit(db, request, "2fa.recovery_regenerated", user=user)
    db.commit()
    return {"recovery_codes": codes}


# ---- your sessions -----------------------------------------------------------------------


def clean_agent(ua: str | None) -> str | None:
    if not ua:
        return None
    return "".join(c for c in ua if c.isprintable())[:200]


def describe_agent(ua: str | None) -> str:
    """'Firefox on Linux' from a user-agent string (a hint, not proof: clients can lie)."""
    if not ua:
        return "Unknown device"
    browser = next(
        (
            name
            for key, name in (
                ("Edg/", "Edge"),
                ("OPR/", "Opera"),
                ("Firefox/", "Firefox"),
                ("Chrome/", "Chrome"),
                ("Safari/", "Safari"),
                ("curl/", "curl"),
                ("python", "Python script"),
            )
            if key in ua
        ),
        "Browser",
    )
    system = next(
        (
            name
            for key, name in (
                ("Android", "Android"),
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Windows", "Windows"),
                ("Mac OS", "macOS"),
                ("CrOS", "ChromeOS"),
                ("Linux", "Linux"),
            )
            if key in ua
        ),
        "",
    )
    return f"{browser} on {system}" if system else browser


@router.get("/sessions")
def my_sessions(
    found: tuple[Session, User] = Depends(current_session), db: DbSession = Depends(get_db)
):
    """Your own signed-in sessions, newest first."""
    current, user = found
    rows = db.scalars(
        select(Session)
        .where(Session.user_id == user.id, Session.expires_at > utcnow())
        .order_by(Session.created_at.desc())
    ).all()
    return [
        {
            "id": s.id,
            "created_at": s.created_at,
            "expires_at": s.expires_at,
            "source_ip": s.source_ip,
            "device": describe_agent(s.user_agent),
            "current": s.id == current.id,
        }
        for s in rows
    ]


@router.delete("/sessions/{session_id}")
def end_session(
    session_id: int,
    request: Request,
    found: tuple[Session, User] = Depends(current_session),
    db: DbSession = Depends(get_db),
):
    """Sign out one of your other sessions (use logout for this one)."""
    current, user = found
    target = db.get(Session, session_id)
    if target is None or target.user_id != user.id:  # someone else's: same answer as missing
        raise HTTPException(status_code=404, detail="Session not found")
    if target.id == current.id:
        raise HTTPException(status_code=400, detail="That's this session: use Sign out")
    db.delete(target)
    write_audit(db, request, "session.revoke", user=user, detail=f"session {session_id}")
    db.commit()
    return {"ok": True}


@router.post("/sessions/revoke-others")
def end_other_sessions(
    request: Request,
    found: tuple[Session, User] = Depends(current_session),
    db: DbSession = Depends(get_db),
):
    current, user = found
    n = accounts.revoke_sessions(db, user, keep_session_id=current.id)
    write_audit(db, request, "session.revoke", user=user, detail=f"{n} other sessions")
    db.commit()
    return {"revoked": n}
