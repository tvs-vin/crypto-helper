"""A health summary for super: what the server can see about itself (no root actions)."""

import platform
import time
from pathlib import Path

from alembic.runtime.migration import MigrationContext
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from app import balance_history, migrate
from app.db import get_db
from app.deps import current_user
from app.models import User
from app.prices import history

router = APIRouter(prefix="/api/system", tags=["system"])
STARTED = time.time()


@router.get("/status")
def status(request: Request, me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if not me.is_super:
        raise HTTPException(status_code=403, detail="Only super can see the system status")
    from app.cli.info import package_version, version_string

    settings = request.app.state.settings
    prices = request.app.state.prices
    snap = prices.last_snapshot
    backups = Path(settings.state_dir) / "backups"
    latest = None
    if backups.is_dir():
        files = sorted(backups.glob("bot-*.db"), key=lambda p: p.stat().st_mtime)
        if files:
            latest = {
                "name": files[-1].name,
                "modified": files[-1].stat().st_mtime,
                "count": len(files),
            }
    return {
        "version": package_version(),
        "build": version_string(),
        "python": platform.python_version(),
        "uptime_seconds": int(time.time() - STARTED),
        "database": {
            # The request's own connection: opening another one mid-request is a mistake.
            "revision": MigrationContext.configure(db.connection()).get_current_revision(),
            "expected": migrate.head_revision(),
        },
        "prices": {
            "source": prices.provider.name,
            "as_of": snap.as_of if snap else None,
            "stale": bool(snap and snap.stale),
            "last_error": prices.last_error,
        },
        "history": {**history.stats(db), "settings": history.load_settings(db).model_dump()},
        "balance_history": balance_history.stats(db),
        "backups": latest,
        "listening": settings.host,
        "allowed_networks": settings.allowed_networks,
        "commands": {
            "update": "crypto-helper update",
            "doctor": "crypto-helper doctor",
            "backup": "crypto-helper db backup",
            "logs": "crypto-helper service logs -f",
            "restart": "crypto-helper service restart",
        },
    }
