"""12b: live windows. Every write route says what it changes; after a change the signed-in
sessions allowed to see it are told (and nobody else); an account's own access changes reach
it; admins open windows on signed-in desktops; background jobs announce their changes too."""

import re

import pytest

from app import live
from tests.conftest import H
from tests.test_route_audit import routes
from tests.test_users import create, uid
from tests.wallet_helpers import hold, user_with, wallet


class Recorder:
    """Stands in for the hub's publishing; `online` are the accounts with a desktop open."""

    def __init__(self, hub, monkeypatch):
        self.events: list[tuple[int, str, dict]] = []
        self.online: set[int] = set()
        monkeypatch.setattr(
            hub, "publish", lambda u, name, data: self.events.append((u, name, data))
        )
        monkeypatch.setattr(hub, "connected", lambda: sorted(self.online))

    def topics(self, user_id) -> set[str]:
        return {
            t for u, n, d in self.events if u == user_id and n == "changed" for t in d["topics"]
        }

    def named(self, name) -> list[tuple[int, dict]]:
        return [(u, d) for u, n, d in self.events if n == name]

    def clear(self):
        self.events.clear()


@pytest.fixture
def rec(app, logged_in, monkeypatch):
    return Recorder(app.state.hub, monkeypatch)


def test_every_write_route_says_what_it_changes(app):
    unmapped = []
    for method, path, _ in routes(app):
        if method in live.WRITES and path.startswith("/api/"):
            if live.topics_for(method, re.sub(r"\{[^}]+\}", "1", path)) is None:
                unmapped.append(f"{method} {path}")
    assert unmapped == [], "add these to app/live.py ROUTES"
    for topics in (t for _, _, t in live.ROUTES):
        assert set(topics) <= set(live.TOPICS)


def test_a_change_reaches_those_who_may_see_it(logged_in, app, rec):
    viewer = user_with(app, logged_in, "viewer", ["wallets.view"])  # noqa: F841
    pricey = user_with(app, logged_in, "pricey", ["prices.view"])  # noqa: F841
    me, v, p = uid(app, "super"), uid(app, "viewer"), uid(app, "pricey")
    rec.online = {me, v, p}
    rec.clear()
    wallet(logged_in, "Cold")
    assert rec.topics(v) == {"wallets"}  # no audit.view: no audit topic
    assert rec.topics(me) == {"wallets", "audit"}  # your own other tabs too
    assert rec.topics(p) == set()  # can't see wallets: hears nothing
    rec.online = {me, p}  # not signed in: nothing sent
    rec.clear()
    wallet(logged_in, "Hot")
    assert rec.topics(v) == set()


def test_own_topics_only_reach_the_owner(logged_in, app, rec):
    pricey = user_with(app, logged_in, "pricey", ["prices.view"])
    me, p = uid(app, "super"), uid(app, "pricey")
    rec.online = {me, p}
    rec.clear()
    r = pricey.post(
        "/api/price-alerts",
        json={"symbol": "BTC", "fiat": "usd", "kind": "above", "value": "1"},
        headers=H,
    )
    assert r.status_code == 201
    assert rec.topics(p) == {"alerts"}
    assert "alerts" not in rec.topics(me)  # super sees the audit entry, not your alerts
    assert "audit" in rec.topics(me)


def test_failed_writes_and_reads_say_nothing(logged_in, app, rec):
    rec.online = {uid(app, "super")}
    rec.clear()
    logged_in.post("/api/wallets", json={"name": "", "kind": "paper"}, headers=H)  # 422
    logged_in.get("/api/wallets")
    assert rec.events == []


def test_access_changes_reach_that_account(logged_in, app, rec):
    vid = create(logged_in, "viewer", ["wallets.view"]).json()["id"]
    rec.online = {vid, uid(app, "super")}
    rec.clear()
    logged_in.patch(f"/api/users/{vid}", json={"permissions": []}, headers=H)
    assert [u for u, _ in rec.named("me")] == [vid]
    rec.clear()
    logged_in.put(f"/api/apps/accounts/{vid}", json={"apps": ["wallets"]}, headers=H)
    assert [u for u, _ in rec.named("me")] == [vid]
    rec.clear()
    logged_in.put("/api/apps/trades/enabled", json={"enabled": False}, headers=H)
    assert sorted(u for u, _ in rec.named("me")) == sorted(rec.online)  # everyone signed in


# ---- opening a window on someone's desktop ---------------------------------------------------


def test_open_a_window_for_someone(logged_in, app, rec):
    vid = create(logged_in, "viewer", ["wallets.view", "prices.view"]).json()["id"]
    url = f"/api/users/{vid}/open-window"
    r = logged_in.post(url, json={"panel": "overview"}, headers=H)
    assert r.status_code == 409 and "isn't signed in" in r.json()["detail"]
    rec.online = {vid}
    assert logged_in.get("/api/users").json()[1]["online"] is True
    r = logged_in.post(url, json={"panel": "overview"}, headers=H)
    assert r.status_code == 200 and r.json() == {"opened": "overview", "for": "viewer"}
    assert rec.named("open-window") == [(vid, {"panel": "overview", "by": "super"})]
    r = logged_in.post(url, json={"panel": "users"}, headers=H)  # no users.manage
    assert r.status_code == 422 and "can't use that window" in r.json()["detail"]
    assert logged_in.post(url, json={"panel": "start"}, headers=H).status_code == 200  # core
    entry = logged_in.get("/api/audit?q=user.open").json()[0]
    assert entry["detail"] == f"start for viewer (id {vid})"


def test_open_window_rules(logged_in, app, rec, monkeypatch):
    from app.routers import users as users_router

    vid = create(logged_in, "viewer", ["wallets.view"]).json()["id"]
    helper = user_with(app, logged_in, "helper", ["users.manage"])
    rec.online = {vid, uid(app, "super")}
    # A user manager can't reach someone holding permissions they lack, nor super.
    assert helper.post(f"/api/users/{vid}/open-window", json={"panel": "start"},
                       headers=H).status_code == 403  # fmt: skip
    sid = uid(app, "super")
    assert logged_in.post(f"/api/users/{sid}/open-window", json={"panel": "start"},
                          headers=H).status_code == 403  # fmt: skip
    nobody = user_with(app, logged_in, "nobody", ["wallets.view"])
    assert nobody.post(f"/api/users/{vid}/open-window", json={"panel": "start"},
                       headers=H).status_code == 403  # fmt: skip
    monkeypatch.setattr(users_router, "OPEN_PER_MINUTE", 2)
    for _ in range(2):
        logged_in.post(f"/api/users/{vid}/open-window", json={"panel": "start"}, headers=H)
    r = logged_in.post(f"/api/users/{vid}/open-window", json={"panel": "start"}, headers=H)
    assert r.status_code == 429


# ---- background jobs -------------------------------------------------------------------------


def test_jobs_announce_their_changes(logged_in, app, rec):
    me = uid(app, "super")
    rec.online = {me}
    rec.clear()
    app.state.history_job.tick()  # records the first prices
    assert "prices" in rec.topics(me)
    rec.clear()
    hold(logged_in, wallet(logged_in, "Cold")["id"], "BTC", "1")
    rec.clear()
    app.state.balance_job.tick()
    assert rec.topics(me) == {"balances"}


def test_a_background_sync_announces_new_balances(logged_in, app, rec, monkeypatch):
    from app.sync import demo
    from app.sync.engine import sync_wallet
    from tests.test_sync import synced_wallet

    monkeypatch.setattr(demo, "BALANCES", dict(demo.BALANCES))
    w, _ = synced_wallet(logged_in)
    rec.online = {uid(app, "super")}
    rec.clear()
    assert sync_wallet(app.state, w["id"]).ok  # as the background job does: no request
    assert {"wallets", "balances", "trades"} <= rec.topics(uid(app, "super"))
    rec.clear()
    assert sync_wallet(app.state, w["id"]).ok  # nothing changed this time
    assert rec.events == []


def test_fired_alerts_tell_only_their_owner(logged_in, app, rec):
    pricey = user_with(app, logged_in, "pricey", ["prices.view"])
    p = uid(app, "pricey")
    pricey.post(
        "/api/price-alerts",
        json={"symbol": "BTC", "fiat": "usd", "kind": "above", "value": "0.01"},
        headers=H,
    )
    rec.online = {p, uid(app, "super")}
    rec.clear()
    assert app.state.price_alerts.tick()["fired"]
    assert rec.topics(p) == {"alerts"} and rec.topics(uid(app, "super")) == set()
