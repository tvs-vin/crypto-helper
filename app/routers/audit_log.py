from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db import get_db
from app.deps import require_permission
from app.models import AuditLog, User

router = APIRouter(tags=["audit"])


@router.get("/api/audit")
def read_audit(
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(require_permission("audit.view")),
    db: DbSession = Depends(get_db),
):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
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
