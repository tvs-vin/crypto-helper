"""The app catalog and who may use which app. Add new apps here and nowhere else.

An app is a window on the desktop. Using one needs all three of:
- the permissions it needs (the data rules, unchanged),
- the app switched on for the account (`users.apps`; None means every app),
- the app not switched off for everyone (the `apps` app setting).
`super` can always use every app. The server enforces the switches per endpoint with
`require_app(...)` in app/deps.py (next to the endpoint's own permission check); hiding a
window is never the check.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session as DbSession

from app.models import AppSetting, User

SETTINGS_KEY = "apps"


@dataclass(frozen=True)
class App:
    name: str
    needs: frozenset[str]
    description: str
    # How many windows of this app one desktop may have open at once.
    max_windows: int = 1


APPS: dict[str, App] = {
    "wallets": App(
        "Wallets",
        frozenset({"wallets.view"}),
        "Wallet cards, balances, create and edit wallets",
        max_windows=4,
    ),
    "overview": App(
        "Overview",
        frozenset({"prices.view"}),
        "Prices, portfolio value and charts",
        max_windows=4,
    ),
    "transfers": App(
        "Transfers", frozenset({"wallets.view"}), "Practice transfers and history", max_windows=4
    ),
    "trades": App(
        "Trade log",
        frozenset({"wallets.view"}),
        "Trades from your exchanges, and CSV for taxes",
        max_windows=2,
    ),
    "audit": App("Audit log", frozenset({"audit.view"}), "Who did what, and when", max_windows=4),
    "users": App("Users", frozenset({"users.manage"}), "Create and manage accounts"),
    "apps": App("App manager", frozenset({"apps.manage"}), "Choose which apps each account uses"),
    "services": App(
        "Services", frozenset({"services.manage"}), "Turn services and features on and off"
    ),
    "console": App(
        "Console", frozenset({"console.use"}), "Run status, doctor, logs and other checks"
    ),
    "terminal": App(
        "Terminal", frozenset({"terminal.use"}), "The VM's login prompt", max_windows=3
    ),
}
# Always available, never switchable: account security (password, 2FA, sessions) lives there.
CORE_APPS = ("settings", "notifications", "help", "start")


def max_windows(panel: str) -> int:
    return APPS[panel].max_windows if panel in APPS else 1


class AppSwitches(BaseModel):
    """Server-wide switches. An app listed in `disabled` is off for everyone except super."""

    model_config = ConfigDict(extra="forbid")
    disabled: list[str] = []

    @field_validator("disabled")
    @classmethod
    def _known(cls, v):
        unknown = sorted(set(v) - set(APPS))
        if unknown:
            raise ValueError(f"unknown apps: {', '.join(unknown)}")
        return sorted(set(v))


def load_switches(db: DbSession) -> AppSwitches:
    row = db.get(AppSetting, SETTINGS_KEY)
    return AppSwitches(**row.value) if row else AppSwitches()


def save_switches(db: DbSession, switches: AppSwitches, actor: str | None) -> None:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        db.add(AppSetting(key=SETTINGS_KEY, value=switches.model_dump(), updated_by=actor))
    else:
        row.value = switches.model_dump()
        row.updated_by = actor


def chosen_apps(user: User) -> set[str]:
    """The apps switched on for this account (None stored = every app)."""
    if user.apps is None:
        return set(APPS)
    return set(user.apps) & set(APPS)


def why_not(user: User, app_id: str, switches: AppSwitches, perms: set[str] | None) -> str | None:
    """None if the account can use the app, else a short reason for the person.
    perms=None checks only the switches: endpoints do that, because each endpoint checks its
    own permission anyway (e.g. sending a transfer needs transfers.create, not wallets.view)."""
    app = APPS[app_id]
    if user.is_super:
        return None
    if app_id in switches.disabled:
        return f"The {app.name} app is turned off for everyone"
    if app_id not in chosen_apps(user):
        return f"The {app.name} app is turned off for your account"
    missing = app.needs - perms if perms is not None else set()
    if missing:
        return f"The {app.name} app needs {', '.join(sorted(missing))}"
    return None


def usable_apps(user: User, switches: AppSwitches, perms: set[str]) -> list[str]:
    return [a for a in APPS if why_not(user, a, switches, perms) is None]
