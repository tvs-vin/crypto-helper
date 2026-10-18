import re

from fastapi import Request
from sqlalchemy.orm import Session as DbSession

from app.models import AuditLog, User

_USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")


def safe_username(raw: str) -> str:
    """A login name typed into the wrong field could be a password: only log well-formed names."""
    return raw if _USERNAME_RE.match(raw) else "<invalid>"


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def record(
    db: DbSession,
    action: str,
    *,
    user_id: int | None,
    username: str | None,
    detail: str = "",
    source_ip: str | None = None,
) -> None:
    """Add an audit row to the current transaction (the caller commits)."""
    db.add(
        AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            detail=detail,
            source_ip=source_ip,
        )
    )


def write_audit(
    db: DbSession,
    request: Request,
    action: str,
    *,
    user: User | None = None,
    username: str | None = None,
    detail: str = "",
) -> None:
    """Audit an HTTP action; `user` is the actor."""
    record(
        db,
        action,
        user_id=user.id if user else None,
        username=user.username if user else username,
        detail=detail,
        source_ip=client_ip(request),
    )
