"""12a: the onboarding API. Steps per account (only what its permissions allow), super's server
steps, ticking by doing vs ticking by finishing, and who may tick what."""

from tests.conftest import H
from tests.test_users import PW2, as_user, create
from tests.wallet_helpers import user_with, wallet


def steps(summary, part="account"):
    return {s["id"]: s["done"] for s in summary[part]}


def test_super_sees_the_server_and_every_step(logged_in):
    s = logged_in.get("/api/onboarding").json()
    assert s["show"] is True and s["restricted"] is None
    assert list(steps(s, "server")) == ["key_backup", "network", "services", "data", "people"]
    assert list(steps(s)) == [
        "welcome", "twofa", "personalise", "watchlist", "wallets", "sync", "alerts",
        "notifications", "tour",
    ]  # fmt: skip
    assert s["done"] == 0 and s["total"] == 14


def test_a_viewer_gets_only_their_steps(logged_in, app):
    viewer = user_with(app, logged_in, "viewer", ["wallets.view", "prices.view"])
    s = viewer.get("/api/onboarding").json()
    assert s["server"] is None
    assert list(steps(s)) == [
        "welcome", "twofa", "personalise", "watchlist", "alerts", "notifications", "tour",
    ]  # fmt: skip
    assert viewer.post("/api/onboarding/steps/network", headers=H).status_code == 403


def test_steps_tick_themselves_from_what_is_set_up(logged_in):
    logged_in.patch("/api/me/preferences", json={"watchlist": ["BTC"]}, headers=H)
    wallet(logged_in, "Cold")
    logged_in.post(
        "/api/price-alerts",
        json={"symbol": "BTC", "kind": "above", "value": "100000", "fiat": "usd"},
        headers=H,
    )
    create(logged_in, "bob", ["wallets.view"])
    s = logged_in.get("/api/onboarding").json()
    assert steps(s)["watchlist"] and steps(s)["wallets"] and steps(s)["alerts"]
    assert steps(s, "server")["people"] is True  # someone was invited
    assert not steps(s)["sync"]


def test_finishing_steps_and_the_walkthrough(logged_in):
    for step in ("welcome", "tour", "key_backup", "network"):
        r = logged_in.post(f"/api/onboarding/steps/{step}", headers=H)
        assert r.status_code == 200
    s = r.json()
    assert steps(s)["welcome"] and steps(s)["tour"]
    assert steps(s, "server")["key_backup"] and steps(s, "server")["network"]
    details = [e["detail"] for e in logged_in.get("/api/audit?q=onboarding.server").json()]
    assert details == ["network", "key_backup"]  # server steps are on record; yours aren't
    assert logged_in.post("/api/onboarding/steps/nonsense", headers=H).status_code == 422
    assert logged_in.post("/api/onboarding/finish", headers=H).json()["show"] is False
    assert logged_in.get("/api/onboarding").json()["show"] is False
    assert logged_in.post("/api/onboarding/restart", headers=H).json()["show"] is True
    assert steps(logged_in.get("/api/onboarding").json())["tour"] is True  # progress kept


def test_server_progress_is_shared_account_progress_is_not(logged_in, app):
    logged_in.post("/api/onboarding/steps/tour", headers=H)
    other = user_with(app, logged_in, "other", ["prices.view"])
    assert steps(other.get("/api/onboarding").json())["tour"] is False


def test_a_rule_shows_in_the_walkthrough(logged_in, app):
    create(logged_in, "newbie", ["prices.view"], must_change_password=True)
    u = as_user(app, "newbie")
    s = u.get("/api/onboarding").json()  # readable while the rule is pending
    assert s["restricted"] == "password" and steps(s)["password"] is False
    r = u.post("/api/onboarding/finish", headers=H)
    assert r.status_code == 403 and r.json()["restricted"] == "password"
    u.post(
        "/api/auth/password",
        json={"current_password": PW2, "new_password": "my-own-passphrase-9"},
        headers=H,
    )
    s = u.get("/api/onboarding").json()
    assert s["restricted"] is None and steps(s)["password"] is True  # kept as done
