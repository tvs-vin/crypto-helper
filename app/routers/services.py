"""The Services window (services.manage): system services through the agent, feature
switches, and the self-test.

Turning system services on and off needs the agent (app/agent); without it the window still
shows and changes the feature switches and runs the self-test."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DbSession

from app import features
from app.agent.client import AgentError, AgentUnavailable, call
from app.audit import write_audit
from app.db import begin_immediate, get_db
from app.deps import require_app, require_permission
from app.models import User
from app.prices import history

router = APIRouter(prefix="/api/services", tags=["services"])
manage = require_permission("services.manage")
in_app = [Depends(require_app("services"))]
AGENT_COMMAND = "sudo crypto-helper agent enable"


def _agent(request: Request, op: str, actor: User, **args) -> dict:
    try:
        return call(request.app.state.settings.agent_socket, op, actor.username, **args)
    except AgentUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail=f"The agent isn't available ({e}). Turn it on from the VM: {AGENT_COMMAND}",
        ) from None
    except AgentError as e:
        raise HTTPException(status_code=502, detail=f"The agent couldn't do that: {e}") from None


def _feature_state(db: DbSession) -> dict:
    return {**features.load(db).model_dump(), "price_history": history.load_settings(db).enabled}


@router.get("", dependencies=in_app)
def overview(request: Request, actor: User = Depends(manage), db: DbSession = Depends(get_db)):
    from app.cli.database import latest_backup
    from app.embeds.options import base_url

    settings = request.app.state.settings
    try:
        services = call(settings.agent_socket, "status", actor.username, timeout=5)["services"]
        agent = {"available": True}
    except (AgentUnavailable, AgentError) as e:
        services = None
        agent = {"available": False, "reason": str(e), "command": AGENT_COMMAND}
    try:
        last = latest_backup(settings)
        backup = {"name": last.name, "modified": last.stat().st_mtime} if last else None
    except OSError:
        backup = None
    return {
        "agent": agent,
        "services": services,
        "embed": {"enabled": settings.embed_enabled, "links": base_url(settings)},
        "backup": backup,
        "features": _feature_state(db),
        "selftest": request.app.state.selftest.status(),
    }


class FeatureChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_wallets: bool | None = None
    practice_transfers: bool | None = None
    practice_prices: bool | None = None
    price_history: bool | None = None


@router.put("/features", dependencies=in_app)
def change_features(
    body: FeatureChange,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    change = body.model_dump(exclude_none=True)
    if not change:
        raise HTTPException(status_code=422, detail="Nothing to change")
    if "price_history" in change:
        h = history.load_settings(db)
        h.enabled = change.pop("price_history")
        history.save_settings(db, h, actor.username)
    if change:
        current = features.load(db).model_dump()
        features.save(db, features.Features(**{**current, **change}), actor.username)
    if body.practice_prices is not None:
        request.app.state.prices.invalidate()
    write_audit(
        db,
        request,
        "services.feature",
        user=actor,
        detail=", ".join(
            f"{k} {'on' if v else 'off'}" for k, v in body.model_dump(exclude_none=True).items()
        ),
    )
    db.commit()
    return _feature_state(db)


class Switch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: bool


def _audited_agent_call(request, db, actor, action: str, detail: str, op: str, **args):
    # Let go of the database write lock while the agent works (starting the embed server
    # can take seconds); take it again only to record what happened.
    db.commit()
    try:
        result = _agent(request, op, actor, **args)
        outcome = "done"
    except HTTPException as e:
        result, outcome = e, f"failed: {e.detail}"
    begin_immediate(db)
    write_audit(db, request, action, user=actor, detail=f"{detail}: {outcome}")
    db.commit()
    if isinstance(result, HTTPException):
        raise result
    return result


@router.post("/{service}/switch", dependencies=in_app)
def switch(
    service: str,
    body: Switch,
    request: Request,
    actor: User = Depends(manage),
    db: DbSession = Depends(get_db),
):
    if service not in ("embed", "backups"):
        raise HTTPException(status_code=404, detail="No such switchable service")
    return _audited_agent_call(
        request,
        db,
        actor,
        "services.switch",
        f"{service} {'on' if body.on else 'off'}",
        "service.set",
        service=service,
        on=body.on,
    )


@router.post("/{service}/restart", dependencies=in_app)
def restart(
    service: str, request: Request, actor: User = Depends(manage), db: DbSession = Depends(get_db)
):
    if service not in ("web", "embed"):
        raise HTTPException(status_code=404, detail="No such restartable service")
    return _audited_agent_call(
        request, db, actor, "services.restart", service, "service.restart", service=service
    )


@router.post("/backups/run", dependencies=in_app)
def run_backup(request: Request, actor: User = Depends(manage), db: DbSession = Depends(get_db)):
    return _audited_agent_call(request, db, actor, "services.backup", "backup now", "backup.run")


@router.post("/selftest", dependencies=in_app, status_code=202)
def start_selftest(
    request: Request, actor: User = Depends(manage), db: DbSession = Depends(get_db)
):
    if not request.app.state.selftest.start(actor.username):
        return JSONResponse({"detail": "A self-test is already running"}, status_code=409)
    write_audit(db, request, "services.selftest", user=actor, detail="started")
    db.commit()
    return request.app.state.selftest.status()


@router.get("/selftest", dependencies=in_app)
def selftest_status(request: Request, _: User = Depends(manage)):
    return request.app.state.selftest.status()
