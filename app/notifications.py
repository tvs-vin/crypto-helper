"""Notifications: stored per user, shown live while they're signed in.

`notify()` adds them to the caller's transaction; they're pushed to open browsers only after
that transaction commits (so nothing is announced that then gets rolled back). Each person
chooses per category whether they want them (preferences.notifications); admins always get
security notifications, whatever they chose.
"""

import asyncio
import json
import logging
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session as DbSession

from app.deps import effective_permissions
from app.models import Notification, User
from app.timeutil import utcnow

log = logging.getLogger(__name__)

CATEGORIES = {
    "security": "Security: sign-ins, password and 2FA changes, lockouts",
    "system": "System: backups, updates, services, the self-test",
    "prices": "Price alerts",
    "messages": "Messages from admins",
}
LEVELS = ("info", "warning", "critical")
KEEP_PER_USER = 500
KEEP_DAYS = 90


def is_admin(user: User) -> bool:
    return user.is_super or "users.manage" in effective_permissions(user)


def wants(user: User, category: str, channel: str = "inapp") -> bool:
    prefs = ((user.preferences or {}).get("notifications") or {}).get("channels") or {}
    choice = (prefs.get(category) or {}).get(channel)
    if category == "security" and channel == "inapp" and is_admin(user):
        return True  # admins can't miss security notifications
    return True if choice is None and channel == "inapp" else bool(choice)


class Hub:
    """Open notification streams, by user id. Publishing is safe from any thread."""

    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.streams: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self, user_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.streams[user_id].add(q)
        return q

    def unsubscribe(self, user_id: int, q: asyncio.Queue) -> None:
        self.streams[user_id].discard(q)

    def publish(self, user_id: int, event_name: str, data: dict) -> None:
        if not self.loop or not self.streams.get(user_id):
            return
        payload = (event_name, json.dumps(data))
        for q in list(self.streams[user_id]):
            self.loop.call_soon_threadsafe(_put, q, payload)


def _put(q: asyncio.Queue, item) -> None:
    try:
        q.put_nowait(item)
    except asyncio.QueueFull:  # a stuck browser: it reloads the list when it catches up
        pass


def out(n: Notification) -> dict:
    return {
        "id": n.id,
        "category": n.category,
        "level": n.level,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "sender": n.sender,
        "created_at": n.created_at.isoformat(timespec="seconds"),
        "read": n.read_at is not None,
    }


def notify(
    db: DbSession,
    hub: Hub | None,
    recipients,
    *,
    category: str,
    title: str,
    body: str = "",
    level: str = "info",
    link: str | None = None,
    sender: str = "system",
) -> list[Notification]:
    """Store a notification for each recipient who wants this category (in the caller's
    transaction), and push it live once that transaction commits."""
    assert category in CATEGORIES and level in LEVELS
    made = []
    for user in recipients:
        if not user.is_active or not wants(user, category):
            continue
        n = Notification(user_id=user.id, category=category, level=level, title=title[:120],
                         body=body[:1000], link=link, sender=sender[:64])  # fmt: skip
        db.add(n)
        made.append(n)
    if made:
        db.flush()
        pending = db.info.setdefault("notify_after_commit", [])
        pending += [(hub, n.user_id, out(n)) for n in made]
        for user_id in {n.user_id for n in made}:
            _trim(db, user_id)
    return made


def everyone(db: DbSession) -> list[User]:
    return list(db.scalars(select(User).where(User.is_active.is_(True))))


def admins(db: DbSession) -> list[User]:
    return [u for u in everyone(db) if is_admin(u)]


def _trim(db: DbSession, user_id: int) -> None:
    keep = select(Notification.id).where(Notification.user_id == user_id)
    keep = keep.order_by(Notification.id.desc()).limit(KEEP_PER_USER)
    db.execute(
        delete(Notification).where(Notification.user_id == user_id, Notification.id.not_in(keep))
    )


def sweep(db: DbSession) -> int:
    """Drop notifications older than KEEP_DAYS."""
    r = db.execute(
        delete(Notification).where(Notification.created_at < utcnow() - timedelta(days=KEEP_DAYS))
    )
    return r.rowcount or 0


@event.listens_for(DbSession, "after_commit")
def _publish(session: DbSession) -> None:
    for hub, user_id, data in session.info.pop("notify_after_commit", []):
        if hub is not None:
            hub.publish(user_id, "notification", data)


@event.listens_for(DbSession, "after_rollback")
def _forget(session: DbSession) -> None:
    session.info.pop("notify_after_commit", None)
