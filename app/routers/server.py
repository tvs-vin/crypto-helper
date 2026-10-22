"""Server setup from the browser (12a onboarding), super only: where the web UI listens and who
may connect. The change is written by the agent (the config file is root's), which puts the old
settings back by itself unless the browser confirms within netconfig.REVERT_SECONDS."""

import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app import netconfig
from app.agent.client import AgentError, AgentUnavailable, call
from app.audit import client_ip, write_audit
from app.db import begin_immediate, get_db
from app.deps import current_user
from app.models import User
from app.netaccess import parse_hosts
from app.routers.services import AGENT_COMMAND

router = APIRouter(prefix="/api/server", tags=["server"])


def super_only(me: User = Depends(current_user)) -> User:
    if not me.is_super:
        raise HTTPException(status_code=403, detail="Only super can change the server's setup")
    return me


def _agent(request: Request, op: str, actor: User, **args) -> dict:
    try:
        return call(request.app.state.settings.agent_socket, op, actor.username, **args)
    except AgentUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail=f"The agent isn't available ({e}). Turn it on from the VM: {AGENT_COMMAND}",
        ) from None
    except AgentError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


def _ip(value) -> str | None:
    try:
        return str(ipaddress.ip_address(value))
    except (TypeError, ValueError):
        return None


def _via(request: Request) -> str | None:
    """The address of this machine the browser reached (it has to stay)."""
    server = request.scope.get("server")
    return _ip(server[0]) if server else None


class NetworkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hosts: list[str] = Field(min_length=1, max_length=netconfig.MAX_HOSTS)
    allowed_networks: list[str] = Field(min_length=1, max_length=netconfig.MAX_NETWORKS)


@router.get("/network")
def get_network(request: Request, me: User = Depends(super_only)):
    s = request.app.state.settings
    hosts = parse_hosts(s.host)
    state = None
    try:
        state = call(s.agent_socket, "network.state", me.username, timeout=5)
    except (AgentUnavailable, AgentError):
        pass
    return {
        "hosts": hosts,
        "port": s.port,
        "allowed_networks": [n.strip() for n in s.allowed_networks.split(",") if n.strip()],
        "addresses": [
            {**a, "listening": a["address"] in hosts} for a in netconfig.local_addresses()
        ],
        "you": {"client_ip": _ip(client_ip(request)), "via": _via(request)},
        "agent": state is not None,
        "pending": bool(state and state["pending"]),
        "seconds_left": state["seconds_left"] if state else 0,
        "confirm_within": netconfig.REVERT_SECONDS,
        "boot": request.app.state.boot_id,
        # Without the agent: what to put in /etc/crypto-helper/config.env by hand.
        "manual": {
            "file": "/etc/crypto-helper/config.env",
            "then": "sudo crypto-helper service restart",
            "agent": AGENT_COMMAND,
        },
    }


@router.put("/network")
def put_network(
    body: NetworkIn, request: Request, me: User = Depends(super_only), db=Depends(get_db)
):
    s = request.app.state.settings
    try:
        hosts, nets = netconfig.check(body.hosts, body.allowed_networks)
    except netconfig.NetConfigError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    current = parse_hosts(s.host)
    for h in hosts:
        if h not in current and not netconfig.is_local(h):
            raise HTTPException(status_code=422, detail=f"{h} isn't an address of this machine.")
    via = _via(request)
    if via and via not in hosts:
        raise HTTPException(
            status_code=422,
            detail=f"Keep {via}: it's the address you're using right now. Add the new one, "
            "open the app there, then remove this one.",
        )
    you = _ip(client_ip(request))
    if you and not any(ipaddress.ip_address(you) in ipaddress.ip_network(n) for n in nets):
        raise HTTPException(
            status_code=422,
            detail=f"Your browser connects from {you}, which none of these networks include: "
            "you'd be shut out.",
        )
    before = f"listen {s.host}; allow {s.allowed_networks}"
    after = f"listen {','.join(hosts)}; allow {','.join(nets)}"
    write_audit(db, request, "server.network", user=me, detail=f"{before} -> {after}")
    db.commit()  # don't hold the write lock while the agent works
    return _agent(request, "network.set", me, hosts=hosts, allowed_networks=nets)


@router.post("/network/confirm")
def confirm_network(request: Request, me: User = Depends(super_only), db=Depends(get_db)):
    """Called by the browser once it reached the server again after the change."""
    db.commit()  # write requests start with the lock taken: not while the agent works
    out = _agent(request, "network.confirm", me)
    begin_immediate(db)
    write_audit(db, request, "server.network.confirm", user=me, detail="kept")
    db.commit()
    return out
