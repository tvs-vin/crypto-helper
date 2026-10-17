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
    "system": "System: backups, updates, services, disk space, prices, the self-test",
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
    _queue_outside(db, recipients, category, level, title[:120], body[:1000])
    if made:
        db.flush()
        pending = db.info.setdefault("notify_after_commit", [])
        pending += [(hub, n.user_id, out(n)) for n in made]
        for user_id in {n.user_id for n in made}:
            _trim(db, user_id)
    return made


def _queue_outside(db: DbSession, recipients, category, level, title, body) -> None:
    """Outbox entries for each recipient's outside channels that want this category."""
    from app.models import Delivery, NotificationChannel

    for user in recipients:
        if not user.is_active or not wants(user, category, "discord"):
            continue
        ch = db.scalar(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user.id, NotificationChannel.kind == "discord"
            )
        )
        if ch is not None:
            when = quiet_until(user, level) or utcnow()
            db.add(Delivery(channel_id=ch.id, category=category, level=level, title=title,
                            body=body, next_attempt_at=when))  # fmt: skip


def quiet_until(user: User, level: str, now=None):
    """If it's the person's quiet hours, when they end (UTC); None otherwise. Critical
    notifications aren't held back."""
    prefs = (user.preferences or {}).get("notifications") or {}
    start, end = prefs.get("quiet_from"), prefs.get("quiet_to")
    if level == "critical" or not start or not end or start == end:
        return None
    offset = timedelta(minutes=int(prefs.get("utc_offset_minutes") or 0))
    now = now or utcnow()
    local = now + offset
    s_min = int(start[:2]) * 60 + int(start[3:])
    e_min = int(end[:2]) * 60 + int(end[3:])
    t = local.hour * 60 + local.minute
    inside = (s_min <= t < e_min) if s_min < e_min else (t >= s_min or t < e_min)
    if not inside:
        return None
    wait = (e_min - t) % (24 * 60)
    return (local + timedelta(minutes=wait)).replace(second=0, microsecond=0) - offset


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


# ---- sending outside -------------------------------------------------------------------------

MAX_ATTEMPTS = 6


class DeliveryWorker:
    """Sends due outbox entries. Retries with backoff; respects Discord's rate limits; gives up
    (and says so on the channel) when the webhook is gone."""

    def __init__(self, session_factory, secret_box, poster=None):
        self.factory = session_factory
        self.box = secret_box
        self.poster = poster  # tests swap in a recorder; default: app.discord.post

    def tick(self) -> int:
        from app import discord
        from app.db import IMMEDIATE
        from app.models import Delivery, NotificationChannel

        post = self.poster or discord.post
        sent = 0
        with self.factory() as db:
            due = db.scalars(
                select(Delivery)
                .where(Delivery.status == "pending", Delivery.next_attempt_at <= utcnow())
                .order_by(Delivery.id)
                .limit(20)
            ).all()
            jobs = []
            for d in due:
                ch = db.get(NotificationChannel, d.channel_id)
                jobs.append((d.id, ch.id, self.box.decrypt(ch.secret_encrypted),
                             discord.payload(d.category, d.level, d.title, d.body)))  # fmt: skip
            db.commit()
        # Network calls happen with no database session open.
        results = []
        for delivery_id, channel_id, url, data in jobs:
            try:
                post(url, data)
                results.append((delivery_id, channel_id, None))
                sent += 1
            except discord.WebhookError as e:
                results.append((delivery_id, channel_id, e))
                if e.retry_after:  # slow down for everything this round
                    break
        with self.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            for delivery_id, channel_id, err in results:
                d, ch = db.get(Delivery, delivery_id), db.get(NotificationChannel, channel_id)
                if d is None or ch is None:
                    continue
                d.attempts += 1
                if err is None:
                    d.status, ch.last_ok_at, ch.failures, ch.last_error = "sent", utcnow(), 0, None
                    continue
                d.last_error = ch.last_error = str(err)[:200]
                ch.failures += 1
                if err.final or d.attempts >= MAX_ATTEMPTS:
                    d.status = "failed"
                else:
                    wait = err.retry_after or min(600, 15 * 2 ** (d.attempts - 1))
                    d.next_attempt_at = utcnow() + timedelta(seconds=wait)
            # Keep the outbox small: done entries older than a week go.
            db.execute(
                delete(Delivery).where(
                    Delivery.status != "pending", Delivery.created_at < utcnow() - timedelta(days=7)
                )
            )
            db.commit()
        return sent

    async def run_forever(self, every: float = 5.0) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # keep going; the next pass retries
                log.exception("notification delivery pass failed")
            await asyncio.sleep(every)
