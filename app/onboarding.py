"""Onboarding (12a): what's left to set up, for each account and (for super) for the server.

Steps that can be seen in the data (2FA on, a wallet exists, a Discord webhook saved) are
worked out from it, so the checklist ticks itself; steps that are about looking at something
(the tour, the network settings) are ticked when the person finishes them in the walkthrough.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.deps import effective_permissions, requires_2fa
from app.models import (
    Alert,
    AppSetting,
    NotificationChannel,
    PriceAlert,
    User,
    Wallet,
    WalletSource,
)

SERVER_KEY = "onboarding"

# Steps ticked by finishing them in the walkthrough (the rest come from the data).
ACCOUNT_MARKS = {"welcome", "personalise", "notifications", "tour"}
SERVER_MARKS = {"key_backup", "network", "services", "data", "people"}


def _count(db: DbSession, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def server_state(db: DbSession) -> dict:
    row = db.get(AppSetting, SERVER_KEY)
    return dict(row.value) if row else {}


def mark_server(db: DbSession, step: str, actor: str) -> None:
    from app.timeutil import utcnow

    state = server_state(db)
    state[step] = utcnow().isoformat(timespec="seconds")
    row = db.get(AppSetting, SERVER_KEY)
    if row is None:
        db.add(AppSetting(key=SERVER_KEY, value=state, updated_by=actor))
    else:
        row.value, row.updated_by = state, actor


def account_state(user: User) -> dict:
    return {"done": [], "finished": False, **(user.onboarding or {})}


def mark_account(user: User, step: str) -> None:
    state = account_state(user)
    if step not in state["done"]:
        state["done"] = [*state["done"], step]
    user.onboarding = state


def account_steps(db: DbSession, user: User, settings) -> list[dict]:
    """The walkthrough for this account, only with what its permissions allow."""
    perms = effective_permissions(user)
    marked = set(account_state(user)["done"])
    prefs = user.preferences or {}

    def step(sid, title, done, **extra):
        return {"id": sid, "title": title, "done": bool(done), **extra}

    out = [step("welcome", "What Crypto Helper does, and never does", "welcome" in marked)]
    if user.must_change_password or "password" in marked:
        out.append(step("password", "Choose your own password", not user.must_change_password))
    need = requires_2fa(user, settings)
    out.append(step("twofa", "Turn on two-factor login", user.totp_enabled, required=need))
    out.append(step("personalise", "Currency, theme and size", "personalise" in marked))
    if "prices.view" in perms:
        out.append(step("watchlist", "Coins to watch", bool(prefs.get("watchlist"))))
    if "wallets.edit" in perms:
        out.append(step("wallets", "Add your first wallet", _count(db, select(Wallet.id)) > 0))
    if "wallets.connect" in perms:
        synced = _count(db, select(WalletSource.wallet_id))  # a row = synced, not typed in
        out.append(step("sync", "Sync a wallet from an exchange or an address", synced > 0))
    if "prices.view" in perms:
        alerts = _count(db, select(PriceAlert.id).where(PriceAlert.user_id == user.id)) + _count(
            db, select(Alert.id).where(Alert.user_id == user.id)
        )
        out.append(step("alerts", "Set an alert", alerts > 0))
    discord = _count(
        db,
        select(NotificationChannel.id).where(
            NotificationChannel.user_id == user.id, NotificationChannel.kind == "discord"
        ),
    )
    out.append(
        step(
            "notifications",
            "Notifications and Discord",
            "notifications" in marked or discord > 0,
        )
    )
    out.append(step("tour", "A tour of the desktop", "tour" in marked))
    return out


def server_steps(db: DbSession) -> list[dict]:
    """super's first-time setup of the server itself."""
    state = server_state(db)
    others = _count(db, select(User.id).where(User.is_super.is_(False)))
    return [
        {"id": "key_backup", "title": "Back up the encryption key", "done": "key_backup" in state},
        {"id": "network", "title": "Where it listens, who may connect", "done": "network" in state},
        {"id": "services", "title": "Services and features", "done": "services" in state},
        {"id": "data", "title": "Prices, history and syncing", "done": "data" in state},
        {"id": "people", "title": "Invite people", "done": "people" in state or others > 0},
    ]


def summary(db: DbSession, user: User, settings) -> dict:
    from app.deps import restriction

    steps = account_steps(db, user, settings)
    server = server_steps(db) if user.is_super else None
    every = steps + (server or [])
    return {
        "restricted": restriction(user, settings),
        # Show the walkthrough on sign-in until it's finished (or skipped) once.
        "show": not account_state(user)["finished"],
        "account": steps,
        "server": server,
        "done": sum(s["done"] for s in every),
        "total": len(every),
    }
