from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app.db import get_db
from app.models import Session, User
from app.permissions import ALL_PERMISSIONS
from app.security import hash_token
from app.timeutil import utcnow

SESSION_COOKIE = "session"


def get_settings(request: Request):
    return request.app.state.settings


def lookup_session(db: DbSession, token: str | None) -> tuple[Session, User] | None:
    """Return the live (session, user) for a cookie token, deleting it if expired."""
    if not token:
        return None
    sess = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if sess is None:
        return None
    if sess.expires_at <= utcnow():
        try:  # tidy up; harmless to skip (a GET holds only a read lock and may lose a race)
            db.delete(sess)
            db.commit()
        except OperationalError:
            db.rollback()
        return None
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    return sess, user


def current_session(request: Request, db: DbSession = Depends(get_db)) -> tuple[Session, User]:
    found = lookup_session(db, request.cookies.get(SESSION_COOKIE))
    if found is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return found


def current_user(found: tuple[Session, User] = Depends(current_session)) -> User:
    return found[1]


def effective_permissions(user: User) -> set[str]:
    """`super` always holds every permission, including ones added in the future."""
    if user.is_super:
        return set(ALL_PERMISSIONS)
    return set(user.permissions or [])


def require_permission(permission: str):
    """Dependency factory: server-side permission check for an endpoint."""

    def checker(user: User = Depends(current_user)) -> User:
        if permission not in effective_permissions(user):
            raise HTTPException(status_code=403, detail="Permission denied")
        return user

    return checker


def session_expiry(hours: int):
    return utcnow() + timedelta(hours=hours)
