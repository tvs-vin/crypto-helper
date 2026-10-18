"""System health notifications (milestone 9c), for the people who run the install (super and
anyone with services.manage).

A background job looks every few minutes at what the server can see: backups, updates, the
services (through the agent, when it's on), the self-test, free disk space and prices. It tells
people when something *goes* wrong and again when it's fixed, never every time it looks. What it
last saw is kept in the database, so a restart doesn't repeat everything.

Everything slow (the agent, the disk, files) is read with no database session open; the write
lock is taken only to record what changed.
"""

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session as DbSession

from app import features
from app import notifications as nt
from app.agent.client import AgentError, AgentUnavailable, call
from app.models import AppSetting, User
from app.timeutil import utcnow

log = logging.getLogger(__name__)

STATE_KEY = "health"
CHECK_EVERY = 300  # seconds
UPDATE_EVERY = 6 * 3600  # asking git is slower and uses the network: a few times a day
BACKUP_OVERDUE_HOURS = 27  # daily, plus the timer's random delay, plus slack
DISK_WARN = (1024**3, 0.05)  # less than 1 GB or 5 % free
DISK_CRITICAL = (300 * 1024**2, 0.02)
PRICES_STALE_MINUTES = 30
ACTOR = "<health>"


@dataclass
class Finding:
    """A condition: bad, fine, or None when it can't be told right now (then nothing changes)."""

    key: str
    bad: bool | None
    title: str = ""
    body: str = ""
    level: str = "warning"
    fixed: str = ""  # title when it clears ("" = say nothing)
    first_time: bool = True  # notify when it's bad the first time it's ever looked at


@dataclass
class Event:
    """Something that happened once (a crash, a failed self-test run)."""

    title: str
    body: str = ""
    level: str = "warning"


@dataclass
class Observation:
    findings: list[Finding] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    memo: dict = field(default_factory=dict)  # counters etc. to remember for next time


def people(db: DbSession) -> list[User]:
    """Who hears about system health: super and anyone who manages services."""
    from app.deps import effective_permissions

    return [
        u for u in nt.everyone(db) if u.is_super or "services.manage" in effective_permissions(u)
    ]


def load_state(db: DbSession) -> dict:
    row = db.get(AppSetting, STATE_KEY)
    return dict(row.value) if row else {}


def save_state(db: DbSession, state: dict) -> None:
    row = db.get(AppSetting, STATE_KEY)
    if row is None:
        db.add(AppSetting(key=STATE_KEY, value=state, updated_by=ACTOR))
    else:
        row.value = state


def _gb(n: int) -> str:
    return f"{n / 1024**3:.1f} GB"


class HealthWatcher:
    def __init__(
        self, settings, session_factory, prices, selftest, hub=None, agent=None, disk=None
    ):
        self.settings = settings
        self.hub = hub  # pushes them to open browsers
        self.factory = session_factory
        self.prices = prices
        self.selftest = selftest
        # Tests swap these for stand-ins.
        self.agent = agent or self._agent_call
        self.disk = disk or shutil.disk_usage
        self._update: dict | None = None
        self._update_checked = 0.0

    def _agent_call(self, op: str, timeout: float = 10) -> dict:
        return call(self.settings.agent_socket, op, ACTOR, timeout=timeout)

    # ---- looking ------------------------------------------------------------------------------

    def observe(self, state: dict, history_on: bool, practice: bool) -> Observation:
        obs = Observation()
        self._services(obs, state)
        self._updates(obs)
        self._selftest(obs, state)
        self._disk(obs)
        self._prices(obs, history_on, practice)
        return obs

    def _services(self, obs: Observation, state: dict) -> None:
        try:
            services = self.agent("status")["services"]
        except (AgentUnavailable, AgentError, KeyError) as e:
            obs.findings.append(
                Finding(
                    "agent",
                    True,
                    "The agent isn't answering",
                    f"The Services window can't switch services until it's back ({e}). On the VM: "
                    "sudo crypto-helper agent enable",
                    fixed="The agent is back",
                    first_time=False,
                )
            )
            obs.findings += [Finding("embed", None), Finding("backup_failed", None)]
            obs.findings.append(self._backup_age(None))
            return
        obs.findings.append(Finding("agent", False, fixed="The agent is back"))

        embed = services.get("embed", {})
        if embed.get("configured"):
            obs.findings.append(
                Finding(
                    "embed",
                    embed.get("active") != "active",
                    "The embed server stopped",
                    f"It's switched on but {embed.get('active', 'not running')}: embeds don't "
                    "load. Services window → restart it.",
                    fixed="The embed server is running again",
                )
            )
        else:
            obs.findings.append(Finding("embed", False))

        for name, label in (("web", "The web app"), ("embed", "The embed server")):
            now = services.get(name, {}).get("restarts")
            if now is None:
                continue
            before = state.get(f"{name}_restarts")
            if before is not None and now > before:
                times = "once" if now - before == 1 else f"{now - before} times"
                obs.events.append(
                    Event(
                        f"{label} crashed and was restarted",
                        f"systemd restarted it {times}. See why: crypto-helper service logs",
                    )
                )
            obs.memo[f"{name}_restarts"] = now

        backups = services.get("backups", {})
        timer_on = backups.get("enabled") == "enabled"
        result = backups.get("last_result", "unknown")
        if not timer_on:
            obs.findings.append(Finding("backup_failed", False))
        elif result == "unknown":
            obs.findings.append(Finding("backup_failed", None))
        else:
            obs.findings.append(
                Finding(
                    "backup_failed",
                    result != "success",
                    "The last backup failed",
                    f"It ended with '{result}'. See why: crypto-helper service logs (or run "
                    "one now from the Services window).",
                    fixed="Backups work again",
                )
            )
        obs.findings.append(self._backup_age(timer_on))

    def _backup_age(self, timer_on: bool | None) -> Finding:
        if not timer_on:
            return Finding("backup_overdue", None if timer_on is None else False)
        from app.cli.database import latest_backup

        try:
            last = latest_backup(self.settings)
        except OSError:
            return Finding("backup_overdue", None)
        if last is None:
            return Finding("backup_overdue", None)  # a new install: the first one is coming
        age_h = (time.time() - last.stat().st_mtime) / 3600
        return Finding(
            "backup_overdue",
            age_h > BACKUP_OVERDUE_HOURS,
            "Backups are overdue",
            f"The newest backup is {age_h / 24:.1f} days old ({last.name}). Is the VM's backup "
            "timer running? crypto-helper service status",
            fixed="Backups are up to date again",
        )

    def _updates(self, obs: Observation) -> None:
        if time.monotonic() - self._update_checked >= UPDATE_EVERY or not self._update_checked:
            self._update_checked = time.monotonic()
            try:
                self._update = self.agent("update.check", timeout=150)
            except (AgentUnavailable, AgentError) as e:
                log.info("update check skipped: %s", e)
                self._update = None
        u = self._update
        if u is None:
            obs.findings.append(Finding("update", None))
            return
        n = u.get("commits", 0)
        obs.findings.append(
            Finding(
                "update",
                bool(u.get("available")),
                "An update is available",
                f"{n} new change{'s' if n != 1 else ''}, newest: {u.get('newest') or '?'}. "
                "Install it on the VM: sudo crypto-helper update",
                level="info",
            )
        )

    def _selftest(self, obs: Observation, state: dict) -> None:
        last = self.selftest.last()
        if not last or not last.get("finished_at"):
            return
        obs.memo["selftest_seen"] = last["finished_at"]
        if last["finished_at"] == state.get("selftest_seen") or last.get("ok"):
            return
        if last.get("checks"):
            what = f"{last.get('failed', 0)} of {last['checks']} checks failed"
        else:
            what = last.get("error") or "it didn't finish"
        obs.events.append(Event("The self-test failed", f"{what}. Details in the Services window."))

    def _disk(self, obs: Observation) -> None:
        try:
            du = self.disk(str(Path(self.settings.state_dir).resolve()))
        except OSError:
            obs.findings.append(Finding("disk", None))
            return
        low = du.free < DISK_WARN[0] or du.free < du.total * DISK_WARN[1]
        very = du.free < DISK_CRITICAL[0] or du.free < du.total * DISK_CRITICAL[1]
        obs.findings.append(
            Finding(
                "disk",
                low,
                "The disk is getting full",
                f"{_gb(du.free)} free of {_gb(du.total)} on the disk holding the database and "
                "backups. Old backups can be deleted, or the VM given more space.",
                level="critical" if very else "warning",
                fixed="There's enough disk space again",
            )
        )

    def _prices(self, obs: Observation, history_on: bool, practice: bool) -> None:
        if not history_on or practice:
            obs.findings.append(Finding("prices", None))
            return
        snap, error = self.prices.last_snapshot, self.prices.last_error
        if snap is None:
            obs.findings.append(
                Finding(
                    "prices",
                    None if not error else True,
                    "Prices aren't updating",
                    f"The price source failed: {error}",
                    fixed="Prices are updating again",
                )
            )
            return
        age = utcnow() - snap.as_of
        stale = snap.stale and age > timedelta(minutes=PRICES_STALE_MINUTES)
        obs.findings.append(
            Finding(
                "prices",
                stale,
                "Prices aren't updating",
                f"The newest prices are {int(age.total_seconds() // 60)} minutes old. The "
                f"price source says: {error or snap.error or 'nothing'}",
                fixed="Prices are updating again",
            )
        )

    # ---- telling ------------------------------------------------------------------------------

    def tick(self) -> list[str]:
        """One look. Returns the titles of what was sent (for tests and the log)."""
        from app.db import IMMEDIATE
        from app.prices import history

        with self.factory() as db:
            state = load_state(db)
            history_on = history.load_settings(db).enabled
            practice = features.load(db).practice_prices
        obs = self.observe(state, history_on, practice)  # no session open while looking

        sent: list[str] = []
        with self.factory() as db:
            db.connection(execution_options={IMMEDIATE: True})
            state = load_state(db)
            seen = dict(state.get("conditions") or {})
            to = people(db)
            for f in obs.findings:
                if f.bad is None:
                    continue
                before = seen.get(f.key)
                if f.bad and before != "bad" and (before == "ok" or f.first_time):
                    nt.notify(
                        db,
                        self.hub,
                        to,
                        category="system",
                        title=f.title,
                        body=f.body,
                        level=f.level,
                        link="services",
                    )
                    sent.append(f.title)
                elif not f.bad and before == "bad" and f.fixed:
                    nt.notify(
                        db,
                        self.hub,
                        to,
                        category="system",
                        title=f.fixed,
                        level="info",
                        link="services",
                    )
                    sent.append(f.fixed)
                seen[f.key] = "bad" if f.bad else "ok"
            for e in obs.events:
                nt.notify(
                    db,
                    self.hub,
                    to,
                    category="system",
                    title=e.title,
                    body=e.body,
                    level=e.level,
                    link="services",
                )
                sent.append(e.title)
            save_state(db, {**state, **obs.memo, "conditions": seen})
            db.commit()
        if sent:
            log.info("health: %s", "; ".join(sent))
        return sent

    async def run_forever(self, every: float = CHECK_EVERY) -> None:
        await asyncio.sleep(30)  # let the server settle after a start
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # one bad look must never stop the watcher
                log.exception("health check failed")
            await asyncio.sleep(every)
