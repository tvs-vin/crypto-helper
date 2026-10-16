"""Console (console.use) and Terminal (terminal.use, only super can grant it).

Both go through the agent and are off until switched on in the Services window. The Terminal
needs 2FA, the password and a code again for every session, and a one-time ticket for its
WebSocket; what's typed is never logged."""

import asyncio
import contextlib
import ipaddress
import json
import secrets
import struct
import threading
import time
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import apps, totp
from app.agent import console as console_commands
from app.agent.client import AgentError, AgentUnavailable, call
from app.agent.terminal import DATA, EXIT, RESIZE, FrameReader, frame
from app.audit import record, write_audit
from app.db import IMMEDIATE, begin_immediate, get_db
from app.deps import (
    SESSION_COOKIE,
    current_session,
    effective_permissions,
    lookup_session,
    require_app,
    require_permission,
)
from app.models import AuditLog, Session, User
from app.netaccess import client_allowed, parse_networks
from app.routers.auth import _decrypt_secret, _register_failure, _verify_password_or_fail
from app.timeutil import utcnow

router = APIRouter(tags=["shell"])
OPENS_PER_HOUR = 10
TICKET_SECONDS = 30
RECHECK_SECONDS = 30
NEED_2FA = "Turn on two-factor login first (Settings → Account)"


def _agent(request: Request, op: str, user: User, **args) -> dict:
    try:
        return call(request.app.state.settings.agent_socket, op, user.username, **args)
    except AgentUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail=f"The agent isn't available ({e}). On the VM: sudo crypto-helper agent enable",
        ) from None
    except AgentError as e:
        raise HTTPException(status_code=409, detail=str(e)[:1].upper() + str(e)[1:]) from None


# ---- Console ---------------------------------------------------------------------------------

console_user = require_permission("console.use")


@router.get("/api/console/commands", dependencies=[Depends(require_app("console"))])
def console_list(_: User = Depends(console_user)):
    return [{"id": k, "description": d} for k, (_, d) in console_commands.COMMANDS.items()]


class ConsoleRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(max_length=32)
    lines: int | None = Field(default=None, ge=20, le=1000)


@router.post("/api/console/run", dependencies=[Depends(require_app("console"))])
def console_run(
    body: ConsoleRun,
    request: Request,
    user: User = Depends(console_user),
    db: DbSession = Depends(get_db),
):
    if body.command not in console_commands.COMMANDS:
        raise HTTPException(status_code=422, detail="Not one of the Console's commands")
    if not user.totp_enabled:
        raise HTTPException(status_code=403, detail=NEED_2FA)
    db.commit()  # don't hold the database write lock while the command runs
    try:
        result = _agent(request, "console.run", user, command=body.command, lines=body.lines)
        outcome = f"exit {result['exit_code']}"
    except HTTPException as e:
        result, outcome = e, f"failed: {e.detail}"
    begin_immediate(db)
    write_audit(db, request, "console.run", user=user, detail=f"{body.command}: {outcome}")
    db.commit()
    if isinstance(result, HTTPException):
        raise result
    return result


# ---- Terminal --------------------------------------------------------------------------------

terminal_user = require_permission("terminal.use")


class TerminalOpen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)
    code: str = Field(min_length=6, max_length=8)
    cols: int = Field(default=100, ge=20, le=500)
    rows: int = Field(default=30, ge=5, le=200)


@router.post("/api/terminal/open", dependencies=[Depends(require_app("terminal"))])
def terminal_open(
    body: TerminalOpen,
    request: Request,
    found: tuple[Session, User] = Depends(current_session),
    _: User = Depends(terminal_user),
    db: DbSession = Depends(get_db),
):
    sess, user = found
    if not user.totp_enabled:
        raise HTTPException(status_code=403, detail=NEED_2FA)
    since = utcnow() - timedelta(hours=1)
    opens = db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.user_id == user.id, AuditLog.action == "terminal.open", AuditLog.time >= since
        )
    )
    if (opens or 0) >= OPENS_PER_HOUR:
        raise HTTPException(
            status_code=429, detail=f"At most {OPENS_PER_HOUR} terminals an hour; try again later"
        )
    _verify_password_or_fail(db, request, user, body.password, "terminal.fail")
    # Codes from the authenticator app only: a recovery code isn't used up for this.
    secret = _decrypt_secret(request, user) if totp.looks_like_totp(body.code) else None
    step = totp.verify_totp(secret, body.code, user.totp_last_step) if secret else None
    if step is None:
        _register_failure(db, request, user)
        write_audit(db, request, "terminal.fail", user=user, detail="bad code")
        db.commit()
        raise HTTPException(status_code=403, detail="That code isn't right")
    user.totp_last_step = step
    user.failed_logins = 0
    db.commit()
    ip = request.client.host if request.client else None
    try:
        ipaddress.ip_address(ip or "")
        where = {"client_ip": ip}
    except ValueError:  # not an address (e.g. a test client): login just won't show one
        where = {}
    opened = _agent(request, "terminal.open", user, cols=body.cols, rows=body.rows, **where)
    ticket = secrets.token_urlsafe(32)
    tickets = request.app.state.terminal_tickets
    now = time.monotonic()
    for t, v in list(tickets.items()):  # forget stale ones
        if v["expires"] < now:
            del tickets[t]
    tickets[ticket] = {
        "user_id": user.id,
        "session_id": sess.id,
        "socket": opened["socket"],
        "session": opened["session"],
        "ip": ip,
        "expires": now + TICKET_SECONDS,
    }
    begin_immediate(db)
    write_audit(db, request, "terminal.open", user=user, detail=f"session {opened['session'][:8]}")
    db.commit()
    return {"ticket": ticket}


def _origin_ok(ws: WebSocket) -> bool:
    """A page on another site can open WebSockets to us with our cookies: only our own pages
    may (the Origin header can't be faked by a web page)."""
    origin = ws.headers.get("origin")
    host = ws.headers.get("host")
    return bool(origin and host and urlsplit(origin).netloc == host)


def _still_allowed(app, token: str | None, user_id: int, session_id: int) -> bool:
    with app.state.session_factory() as db:
        found = lookup_session(db, token)
        if not found or found[0].id != session_id or found[1].id != user_id:
            return False
        user = found[1]
        perms = effective_permissions(user)
        return (
            user.is_active
            and "terminal.use" in perms
            and apps.why_not(user, "terminal", apps.load_switches(db), perms) is None
        )


@router.websocket("/api/terminal/ws")
async def terminal_ws(ws: WebSocket):
    app = ws.app
    networks = parse_networks(app.state.settings.allowed_networks)
    if not client_allowed(ws.client.host if ws.client else None, networks) or not _origin_ok(ws):
        await ws.close(code=4403)
        return
    entry = app.state.terminal_tickets.pop(ws.query_params.get("ticket", ""), None)
    token = ws.cookies.get(SESSION_COOKIE)
    if (
        entry is None
        or entry["expires"] < time.monotonic()
        or not _still_allowed(app, token, entry["user_id"], entry["session_id"])
    ):
        await ws.close(code=4401)
        return
    try:
        reader, writer = await asyncio.open_unix_connection(entry["socket"])
    except OSError:
        await ws.close(code=4404)
        return
    await ws.accept()
    started = time.monotonic()
    frames = FrameReader()

    async def to_terminal():
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                writer.write(frame(DATA, msg["bytes"]))
            elif msg.get("text"):
                try:
                    cols, rows = json.loads(msg["text"])["resize"]
                    writer.write(frame(RESIZE, struct.pack(">HH", int(cols), int(rows))))
                except (ValueError, KeyError, TypeError, struct.error):
                    continue
            await writer.drain()

    async def from_terminal():
        while True:
            data = await reader.read(65536)
            if not data:
                return
            for kind, payload in frames.feed(data):
                if kind == DATA:
                    await ws.send_bytes(payload)
                elif kind == EXIT:
                    return

    async def watchdog():
        while True:
            await asyncio.sleep(RECHECK_SECONDS)
            ok = await asyncio.to_thread(
                _still_allowed, app, token, entry["user_id"], entry["session_id"]
            )
            if not ok:  # signed out, expired, deactivated, or access taken away
                return

    tasks = [asyncio.create_task(t()) for t in (to_terminal, from_terminal, watchdog)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except Exception:
        pass
    finally:
        for t in tasks:
            t.cancel()
        writer.close()  # the bridge hangs up the login session when this closes
        # Record the close first, in its own thread: this cleanup can itself be cancelled
        # (the browser went away), and the audit entry must be written regardless.
        threading.Thread(target=_audit_close, args=(app, entry, time.monotonic() - started)).start()
        with contextlib.suppress(Exception):
            await ws.close()


def _audit_close(app, entry: dict, seconds: float) -> None:
    with app.state.session_factory() as db:
        db.connection(execution_options={IMMEDIATE: True})
        user = db.get(User, entry["user_id"])
        record(
            db,
            "terminal.close",
            user_id=entry["user_id"],
            username=user.username if user else None,
            detail=f"session {entry['session'][:8]} after {int(seconds)} s",
            source_ip=entry["ip"],
        )
        db.commit()
