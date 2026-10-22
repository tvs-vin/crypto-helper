"""Live windows (12b): every window shows the newest data.

After something changes, the server pushes `changed {topics}` over the live stream (the one
notifications use) to every signed-in session allowed to see that kind of data; the browser
turns topics into its bus events and windows reload. Changes made through the API are found by
route (`topics_for`, used by a middleware after each successful write; a test makes sure every
write route is mapped); background jobs call `publish` themselves.

Two more events: `me` tells an account its own access changed (permissions, apps, rules: the
desktop asks /api/auth/me again and closes windows it may no longer use), and `open-window`
(an admin opening a window on someone's desktop, see app/routers/users.py).

Nothing secret or personal is sent: only topic names.
"""

import re

from sqlalchemy import select

from app.deps import effective_permissions
from app.models import User

# Topic -> the permissions needed to hear about it (None: everyone signed in; "own": only the
# account that made the change).
TOPICS: dict[str, set[str] | str | None] = {
    "wallets": {"wallets.view"},
    "transfers": {"wallets.view"},
    "trades": {"wallets.view"},
    "balances": {"wallets.view"},
    "connections": {"wallets.connect"},
    "prices": {"prices.view"},
    "alerts": "own",
    "users": {"users.manage"},
    "apps": {"apps.manage"},
    "services": {"services.manage"},
    "audit": {"audit.view"},
    "embeds": "own",
    "onboarding": "own",
    "backtests": "own",
    "bots": {"bots.view"},
    "themes": None,
    "settings": None,
}

# (method or "*", path regex) -> topics, first match wins. Every write route must match one
# (tests/test_live.py); [] means "nothing other windows show changes".
ROUTES: list[tuple[str, str, list[str]]] = [
    ("*", r"^/api/(auth|setup|terminal|console)(/|$)", []),
    ("*", r"^/api/me/(preferences|wallet-order)$", []),  # your own layout and display
    ("*", r"^/api/trades/export", []),
    ("*", r"^/api/notifications", []),  # notifications push themselves
    ("POST", r"^/api/wallets/\d+/sync$", ["wallets", "trades", "balances"]),
    ("*", r"^/api/wallets/\d+/source$", ["wallets", "connections"]),
    ("*", r"^/api/(wallets|holdings)(/|$)", ["wallets"]),
    ("*", r"^/api/transfers", ["transfers", "wallets"]),
    ("*", r"^/api/(connections|sync)(/|$)", ["connections"]),
    ("*", r"^/api/(coins|prices)(/|$)", ["prices", "settings"]),
    ("*", r"^/api/balance-history", ["settings", "balances"]),
    ("*", r"^/api/(price-alerts|alerts)(/|$)", ["alerts"]),
    ("*", r"^/api/users/\d+/open-window$", []),  # it sends its own event
    ("*", r"^/api/users", ["users"]),
    ("*", r"^/api/apps", ["apps"]),
    ("*", r"^/api/services", ["services", "settings"]),
    ("*", r"^/api/server", ["settings"]),
    ("*", r"^/api/(themes|wallpapers)", ["themes"]),
    ("*", r"^/api/embeds", ["embeds"]),
    ("*", r"^/api/onboarding", ["onboarding"]),
    ("POST", r"^/api/backtests/run$", []),  # runs without saving: nothing changes
    ("*", r"^/api/backtests", ["backtests"]),
    ("*", r"^/api/bots", ["bots"]),
]
_ROUTES = [(m, re.compile(p), t) for m, p, t in ROUTES]


def topics_for(method: str, path: str) -> list[str] | None:
    """The topics a successful write to `path` changes; None if the route isn't mapped."""
    for m, pattern, topics in _ROUTES:
        if m in ("*", method) and pattern.search(path):
            return topics
    return None


def me_targets(method: str, path: str) -> list[int] | str | None:
    """Whose own access a write changes: user ids, "everyone", or None."""
    m = re.match(r"^/api/(users|apps/accounts)/(\d+)$", path)
    if m and method in ("PATCH", "PUT", "DELETE"):
        return [int(m.group(2))]
    if re.match(r"^/api/apps/\w+/enabled$", path):
        return "everyone"  # an app switched on or off for everyone
    return None


def allowed(user: User, topic: str, actor_id: int | None) -> bool:
    need = TOPICS[topic]
    if need == "own":
        return user.id == actor_id
    return need is None or need <= effective_permissions(user)


def recipients(
    db, hub, topics: list[str], actor_id: int | None = None, only: set[int] | None = None
) -> dict[int, list[str]]:
    """Connected accounts -> the topics each may hear about. `only`: just these accounts, each
    counting as the actor (for "own" topics such as their alerts)."""
    ids = hub.connected() if hub else []
    if only is not None:
        ids = [i for i in ids if i in only]
    if not ids or not topics:
        return {}
    out: dict[int, list[str]] = {}
    for user in db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))):
        me = user.id if only is not None else actor_id
        mine = [t for t in topics if allowed(user, t, me)]
        if mine:
            out[user.id] = mine
    return out


def publish(
    state_or_hub, factory, topics: list[str], actor_id: int | None = None, only=None
) -> int:
    """Tell everyone allowed that `topics` changed (background jobs; short read session)."""
    hub = getattr(state_or_hub, "hub", state_or_hub)
    if hub is None or not hub.connected():
        return 0
    with factory() as db:
        to = recipients(db, hub, topics, actor_id, set(only) if only is not None else None)
    for user_id, mine in to.items():
        hub.publish(user_id, "changed", {"topics": mine})
    return len(to)


def tell_me(hub, user_ids) -> None:
    """These accounts' own access changed: their desktops ask again."""
    if hub is None:
        return
    for uid in hub.connected() if user_ids == "everyone" else user_ids:
        hub.publish(uid, "me", {})


WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def after_write(app, method: str, path: str, token: str | None) -> None:
    """Run after a successful API write (in a worker thread): push `changed` and `me`."""
    import logging

    from app.deps import lookup_session

    topics = topics_for(method, path)
    if topics is None:
        logging.getLogger(__name__).warning("live: no topics for %s %s", method, path)
        return
    hub = app.state.hub
    targets = me_targets(method, path)
    if targets:
        tell_me(hub, targets)
    if not topics or not hub.connected():
        return
    with app.state.session_factory() as db:
        found = lookup_session(db, token)
        actor = found[1].id if found else None
        to = recipients(db, hub, [*topics, "audit"], actor)
        db.rollback()  # read only
    for user_id, mine in to.items():
        hub.publish(user_id, "changed", {"topics": mine})
