"""The App manager (apps.manage): which apps each account can use, and server-wide switches.

Same no-escalation rules as user management: never super, never yourself, never an account
holding permissions you don't, and only apps you can use yourself."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import apps
from app.audit import write_audit
from app.db import get_db
from app.deps import effective_permissions, require_app, require_permission
from app.models import User
from app.permissions import PERMISSIONS

router = APIRouter(prefix="/api/apps", tags=["apps"])
manage = require_permission("apps.manage")
in_app = [Depends(require_app("apps"))]


def _mine(actor: User, db: DbSession) -> set[str]:
    """Apps the actor may hand out: the ones they can use themselves."""
    return set(apps.usable_apps(actor, apps.load_switches(db), effective_permissions(actor)))


def _account(u: User, actor: User, switches: apps.AppSwitches, mine: set[str]) -> dict:
    perms = effective_permissions(u)
    locked = None
    if u.is_super:
        locked = "super always has every app"
    elif u.id == actor.id:
        locked = "you can't change your own apps"
    elif not perms <= effective_permissions(actor):
        locked = "has permissions you don't hold"
    return {
        "id": u.id,
        "username": u.username,
        "is_super": u.is_super,
        "is_active": u.is_active,
        "chosen": "all" if u.apps is None else sorted(apps.chosen_apps(u)),
        # Per app: null if usable, else why not (switched off, or a missing permission).
        "status": {a: apps.why_not(u, a, switches, perms) for a in apps.APPS},
        "locked": locked,
    }


@router.get("", dependencies=in_app)
def overview(actor: User = Depends(manage), db: DbSession = Depends(get_db)):
    switches = apps.load_switches(db)
    mine = _mine(actor, db)
    users = db.scalars(select(User).order_by(User.is_super.desc(), User.username)).all()
    return {
        "apps": [
            {
                "id": a,
                "name": app.name,
                "description": app.description,
                "needs": sorted(app.needs),
                "any_of": app.any_of,
                "enabled": a not in switches.disabled,
                "can_grant": a in mine,
            }
            for a, app in apps.APPS.items()
        ],
        "core": list(apps.CORE_APPS),
        "permissions": PERMISSIONS,
        "accounts": [_account(u, actor, switches, mine) for u in users],
    }


class Switch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.put("/{app_id}/enabled", dependencies=in_app)
def switch(
    app_id: str,
    body: Switch,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    """Turn an app on or off for everyone (super keeps it either way)."""
    if app_id not in apps.APPS:
        raise HTTPException(status_code=404, detail="No such app")
    if app_id not in _mine(actor, db):
        raise HTTPException(status_code=403, detail="You can only switch apps you can use")
    switches = apps.load_switches(db)
    disabled = set(switches.disabled)
    if body.enabled:
        disabled.discard(app_id)
    else:
        disabled.add(app_id)
    apps.save_switches(db, apps.AppSwitches(disabled=sorted(disabled)), actor.username)
    write_audit(
        db,
        request,
        "apps.switch",
        user=actor,
        detail=f"{app_id} {'on' if body.enabled else 'off'} for everyone",
    )
    db.commit()
    return {"id": app_id, "enabled": body.enabled}


class AccountApps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # "all" = every app, including ones added later; or an explicit list.
    apps: list[str] | str


@router.put("/accounts/{user_id}", dependencies=in_app)
def set_account_apps(
    user_id: int,
    body: AccountApps,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.is_super:
        raise HTTPException(status_code=403, detail="Super always has every app")
    if target.id == actor.id:
        raise HTTPException(status_code=403, detail="You can't change your own apps")
    if not effective_permissions(target) <= effective_permissions(actor):
        raise HTTPException(status_code=403, detail="That user has permissions you do not hold")
    mine = _mine(actor, db)
    before = apps.chosen_apps(target)
    if body.apps == "all":
        new, stored = set(apps.APPS), None
    elif isinstance(body.apps, list):
        unknown = sorted(set(body.apps) - set(apps.APPS))
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown apps: {', '.join(unknown)}")
        new = set(body.apps)
        stored = sorted(new)
    else:
        raise HTTPException(status_code=422, detail='apps must be a list or "all"')
    # Only what changes counts: you may leave alone apps you can't use yourself, but you
    # can't switch them on or off for someone else.
    changed = before ^ new
    if changed - mine:
        raise HTTPException(
            status_code=403,
            detail=f"You can only switch apps you can use: {', '.join(sorted(changed - mine))}",
        )
    target.apps = stored
    write_audit(
        db,
        request,
        "apps.account",
        user=actor,
        detail=f"{target.username}: "
        + ("all apps" if stored is None else (", ".join(stored) or "no apps")),
    )
    db.commit()
    return _account(target, actor, apps.load_switches(db), mine)
