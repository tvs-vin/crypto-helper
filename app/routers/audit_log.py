from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from app.db import get_db
from app.deps import require_app, require_permission
from app.models import AuditLog, User

router = APIRouter(tags=["audit"])


@router.get("/api/audit", dependencies=[Depends(require_app("audit"))])
def read_audit(
    limit: int = Query(default=100, ge=1, le=1000),
    before_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
    _: User = Depends(require_permission("audit.view")),
    db: DbSession = Depends(get_db),
):
    """Newest first. Page with ?before_id=<last id seen>; ?q= matches action, user or detail."""
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(
            or_(
                AuditLog.action.ilike(like),
                AuditLog.username.ilike(like),
                AuditLog.detail.ilike(like),
            )
        )
    rows = db.scalars(stmt)
    return [
        {
            "id": r.id,
            "time": r.time,
            "user_id": r.user_id,
            "username": r.username,
            "action": r.action,
            "detail": r.detail,
            "source_ip": r.source_ip,
        }
        for r in rows
    ]
