"""Saved desktop layouts: several windows of one app, per-window state, every window saved."""

import pytest

from app.apps import APPS, CORE_APPS
from tests.conftest import H


def win(panel, **kw):
    return {"panel": panel, "x": 10, "y": 10, "w": 600, "h": 400, **kw}


def save(client, windows):
    return client.patch("/api/me/preferences", json={"layout": {"windows": windows}}, headers=H)


def test_every_window_can_be_saved(logged_in):
    """Regression: the App manager and Services windows used to make every save fail."""
    r = save(logged_in, [win(p) for p in (*APPS, *CORE_APPS)])
    assert r.status_code == 200, r.text


def test_several_overviews_with_their_own_state(logged_in):
    windows = [
        win("overview", state={"fiat": "usd", "coin": "BTC", "hours": "24"}),
        win("overview", id="overview:2", state={"fiat": "eur", "coin": "ETH", "hours": "168"}),
        win("overview", id="overview:4"),
    ]
    r = save(logged_in, windows)
    assert r.status_code == 200, r.text
    saved = logged_in.get("/api/me/preferences").json()["layout"]["windows"]
    assert [w["id"] for w in saved] == ["overview", "overview:2", "overview:4"]
    assert saved[1]["state"] == {"fiat": "eur", "coin": "ETH", "hours": "168"}


def test_old_layouts_without_ids_still_load(logged_in):
    assert save(logged_in, [win("wallets"), win("overview")]).status_code == 200
    ids = [w["id"] for w in logged_in.get("/api/me/preferences").json()["layout"]["windows"]]
    assert ids == ["wallets", "overview"]


@pytest.mark.parametrize(
    "windows",
    [
        [win("overview"), win("overview")],  # same window twice
        [win("overview", id="overview:5")],  # over the limit of 4
        [win("settings", id="settings:2")],  # settings is one window only
        [win("services", id="services:2")],
        [win("overview", id="wallets:2")],  # id of another app
        [win("overview", id="overview:1")],  # the first one is plain "overview"
        [win("overview", id="Overview")],
        [win("overview", state={"x": {"nested": True}})],  # plain values only
        [win("overview", state={"Bad key": "a"})],
        [win("overview", state={"coin": "x" * 41})],
        [win("overview", state={f"k{i}": 1 for i in range(9)})],  # at most 8 keys
        [win("overview", id="overview:" + "2" * 20)],
    ],
)
def test_bad_layouts_are_refused(logged_in, windows):
    assert save(logged_in, windows).status_code == 422


@pytest.mark.parametrize("bad", [50, 74, 151, 200, 103, "big"])
def test_scale_is_validated(logged_in, bad):
    r = logged_in.patch("/api/me/preferences", json={"scale": bad}, headers=H)
    assert r.status_code == 422


def test_scale_saves(logged_in):
    assert logged_in.get("/api/me/preferences").json()["scale"] == 100
    r = logged_in.patch("/api/me/preferences", json={"scale": 125}, headers=H)
    assert r.status_code == 200 and r.json()["scale"] == 125
