"""Account operations shared by the HTTP API and the `crypto-helper` CLI.

These change the session but don't commit or audit: the caller does both, so each
action lands in one transaction together with its audit entry.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from app import totp
from app.models import RecoveryCode, Session, User
from app.security import hash_password


def revoke_sessions(db: DbSession, user: User, keep_session_id: int | None = None) -> int:
    stmt = delete(Session).where(Session.user_id == user.id)
    if keep_session_id is not None:
        stmt = stmt.where(Session.id != keep_session_id)
    return db.execute(stmt).rowcount or 0


def set_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    unlock(user)


def unlock(user: User) -> None:
    user.failed_logins = 0
    user.locked_until = None


def issue_recovery_codes(db: DbSession, user: User) -> list[str]:
    """Replace the user's recovery codes. The plain codes are returned once, never stored."""
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = totp.new_recovery_codes()
    for code in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=totp.hash_recovery_code(code)))
    return codes


def recovery_codes_left(db: DbSession, user: User) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(RecoveryCode).where(RecoveryCode.user_id == user.id)
        )
        or 0
    )


def use_recovery_code(db: DbSession, user: User, code: str) -> bool:
    """Consume a matching recovery code. True if one matched."""
    canonical = totp.canonical_recovery(code)
    if canonical is None:
        return False
    rows = db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == user.id)).all()
    for row in rows:
        if totp.recovery_code_matches(row.code_hash, canonical):
            db.delete(row)
            return True
    return False


def reset_2fa(db: DbSession, user: User) -> None:
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_last_step = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
