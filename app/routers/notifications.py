"""Your notifications, a live stream of new ones, and sending them (notifications.send).

The live stream is a server-sent event stream. It must not keep a database session open
(SQLite here isn't in WAL mode, so a long read would hold up writes): it signs in with a short
session, then waits on the in-memory hub, re-checking the session now and then the same way."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from app import apps, discord, notifications
from app.audit import write_audit
from app.db import get_db
from app.deps import SESSION_COOKIE, current_user, lookup_session, require_permission
from app.models import Notification, NotificationChannel, User
from app.secret_guard import find_secret
from app.timeutil import utcnow

router = APIRouter(prefix="/api/notifications", tags=["notifications"])
RECHECK_SECONDS = 30
HEARTBEAT_SECONDS = 20


def _unread(db: DbSession, me: User) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == me.id, Notification.read_at.is_(None))
        )
        or 0
    )


@router.get("")
def list_notifications(
    unread: bool = False,
    limit: int = 50,
    before: int | None = None,
    me: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    stmt = select(Notification).where(Notification.user_id == me.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    if before:
        stmt = stmt.where(Notification.id < before)
    rows = db.scalars(stmt.order_by(Notification.id.desc()).limit(max(1, min(limit, 200)))).all()
    return {"items": [notifications.out(n) for n in rows], "unread": _unread(db, me)}


class MarkRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[int] | None = Field(default=None, max_length=500)  # none: all of them


@router.post("/read")
def mark_read(body: MarkRead, me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    stmt = update(Notification).where(Notification.user_id == me.id, Notification.read_at.is_(None))
    if body.ids is not None:
        stmt = stmt.where(Notification.id.in_(body.ids))
    db.execute(stmt.values(read_at=utcnow()))
    db.commit()
    return {"unread": _unread(db, me)}


@router.delete("/{notification_id}", status_code=204)
def delete_one(
    notification_id: int, me: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != me.id:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(n)
    db.commit()


@router.delete("", status_code=204)
def clear_read(me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Delete the ones already read."""
    for n in db.scalars(
        select(Notification).where(Notification.user_id == me.id, Notification.read_at.is_not(None))
    ):
        db.delete(n)
    db.commit()


# ---- sending ---------------------------------------------------------------------------------


class Send(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: int | str  # a user id, or "all"
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=1000)
    level: str = Field(default="info", pattern=r"^(info|warning|critical)$")
    link: str | None = Field(default=None, max_length=32)


@router.get("/recipients")
def recipients(
    me: User = Depends(require_permission("notifications.send")), db: DbSession = Depends(get_db)
):
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username)).all()
    return [{"id": u.id, "username": u.username} for u in users]


@router.post("/send", status_code=201)
def send(
    body: Send,
    request: Request,
    me: User = Depends(require_permission("notifications.send")),
    db: DbSession = Depends(get_db),
):
    if find_secret(body.title) or find_secret(body.body):
        raise HTTPException(
            status_code=422, detail="That looks like a recovery phrase or key: not sent."
        )
    if body.link is not None and body.link not in (*apps.APPS, *apps.CORE_APPS):
        raise HTTPException(status_code=422, detail="Link to one of the app's windows")
    if body.to == "all":
        targets, label = notifications.everyone(db), "everyone"
    else:
        try:
            target = db.get(User, int(body.to))
        except ValueError:
            target = None
        if target is None or not target.is_active:
            raise HTTPException(status_code=404, detail="No such active user")
        targets, label = [target], target.username
    made = notifications.notify(
        db, request.app.state.hub, targets, category="messages", title=body.title.strip(),
        body=body.body.strip(), level=body.level, link=body.link, sender=me.username,
    )  # fmt: skip
    write_audit(db, request, "notifications.send", user=me, detail=f"to {label}: {body.title[:60]}")
    db.commit()
    # Some people may have switched messages off: say how many got it.
    return {"sent": len(made), "to": label}


# ---- the live stream -------------------------------------------------------------------------


def _session_user(app, token: str | None) -> int | None:
    with app.state.session_factory() as db:
        found = lookup_session(db, token)
        db.commit()
        return found[1].id if found and found[1].is_active else None


@router.get("/stream")
async def stream(request: Request):
    app = request.app
    token = request.cookies.get(SESSION_COOKIE)
    user_id = await run_in_threadpool(_session_user, app, token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    hub: notifications.Hub = app.state.hub
    q = hub.subscribe(user_id)

    async def events():
        try:
            yield "retry: 5000\n\n"
            last_check = asyncio.get_running_loop().time()
            while True:
                try:
                    name, data = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_SECONDS)
                    yield f"event: {name}\ndata: {data}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
                now = asyncio.get_running_loop().time()
                if now - last_check >= RECHECK_SECONDS:
                    last_check = now
                    if await run_in_threadpool(_session_user, app, token) != user_id:
                        yield f"event: signed-out\ndata: {json.dumps({})}\n\n"
                        return
                if await request.is_disconnected():
                    return
        finally:
            hub.unsubscribe(user_id, q)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---- outside channels (Discord) --------------------------------------------------------------


def _channel_out(ch: NotificationChannel) -> dict:
    return {
        "kind": ch.kind,
        "label": ch.label,
        "created_at": ch.created_at.isoformat(timespec="seconds"),
        "last_ok_at": ch.last_ok_at.isoformat(timespec="seconds") if ch.last_ok_at else None,
        "last_error": ch.last_error,
        "failures": ch.failures,
    }


def _mine(db: DbSession, me: User) -> NotificationChannel | None:
    return db.scalar(
        select(NotificationChannel).where(
            NotificationChannel.user_id == me.id, NotificationChannel.kind == "discord"
        )
    )


@router.get("/channels")
def channels(me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    ch = _mine(db, me)
    return {"discord": _channel_out(ch) if ch else None}


class Webhook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=300)


@router.put("/channels/discord")
def set_discord(
    body: Webhook,
    request: Request,
    me: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    try:
        url = discord.check(body.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    ch = _mine(db, me) or NotificationChannel(user_id=me.id, kind="discord")
    ch.secret_encrypted = request.app.state.secret_box.encrypt(url)
    ch.label = discord.mask(url)
    ch.failures, ch.last_error = 0, None
    db.add(ch)
    write_audit(db, request, "notifications.channel", user=me, detail=f"set {ch.label}")
    db.commit()
    return _channel_out(ch)


@router.post("/channels/discord/test")
def test_discord(
    request: Request, me: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    ch = _mine(db, me)
    if ch is None:
        raise HTTPException(status_code=404, detail="No Discord webhook set")
    url = request.app.state.secret_box.decrypt(ch.secret_encrypted)
    db.commit()  # no lock held while talking to Discord
    poster = request.app.state.delivery.poster or discord.post
    try:
        hello = f"Notifications for {me.username} will arrive here."
        poster(url, discord.payload("messages", "info", "Crypto Helper is connected", hello))
        error = None
    except discord.WebhookError as e:
        error = str(e)
    ch = _mine(db, me)
    if error:
        ch.last_error = error[:200]
    else:
        ch.last_ok_at, ch.last_error, ch.failures = utcnow(), None, 0
    db.commit()
    if error:
        raise HTTPException(status_code=502, detail=error)
    return _channel_out(ch)


@router.delete("/channels/discord", status_code=204)
def remove_discord(
    request: Request, me: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    ch = _mine(db, me)
    if ch is not None:
        write_audit(db, request, "notifications.channel", user=me, detail=f"removed {ch.label}")
        db.delete(ch)
        db.commit()
