"""The readiness test clock in a real browser: on a throwaway server started with
BOT_READINESS_TEST_CLOCK=true a day is a minute, the panel says TEST, and "ready" is marked as a
test result that never allows live trading."""

from datetime import timedelta

import pytest

from app.db import IMMEDIATE, make_session_factory
from app.models import Bot
from app.timeutil import utcnow
from tests.ui.conftest import SCREENS, Server, _api, open_window, sign_in
from tests.ui.test_bots import checker, seed
from toolchain.tester.server import SpawnedServer


@pytest.fixture
def clock_server():
    s = SpawnedServer(extra_env={"BOT_READINESS_TEST_CLOCK": "true"})
    s.start()
    _api(s, "POST", "/api/setup", {"token": s.setup_token, "password": s.password})
    yield Server(s)
    s.stop()


def test_the_test_clock(clock_server, page):  # server first: it stops after the page
    server = clock_server
    seed(server)
    cookie = server.admin_cookie()
    plan = {"strategy": "dca", "coins": {"BTC": "100"}, "currency": "usd", "initial": "1000"}
    _, _, b = server.api("POST", "/api/bots", {"name": "Quick test", "params": plan}, cookie)
    steps = [
        ("/api/bots/drill", {"reason": "test drill"}),
        ("/api/bots/rearm", {"confirm": "REARM"}),
        (f"/api/bots/{b['id']}/start", None),
        ("/api/bots/selfcheck", None),
    ]
    for path, body in steps:
        server.api("POST", path, body, cookie)
    # 15 minutes of clean running, as if the bot check had run every minute meanwhile.
    engine, job = checker(server)
    with make_session_factory(engine)() as db:
        db.connection(execution_options={IMMEDIATE: True})  # write lock first, like the app
        bot = db.get(Bot, b["id"])
        bot.state = {**bot.state, "clean_since": (utcnow() - timedelta(minutes=15)).isoformat()}
        db.commit()
    job.tick()
    engine.dispose()
    _, _, r = server.api("GET", "/api/bots/readiness", None, cookie)
    assert r["test_clock"] is True and r["ready"] is True and r["live_allowed"] is False

    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "bots")
    w = page.locator(".window[data-panel=bots]")
    w.locator("details.readiness summary").click()
    w.locator("[data-test-clock=on]").wait_for()
    assert w.locator("details.readiness .badge").inner_text() == "ready (test)"
    assert "test days (minutes)" in w.locator(".ready-bot").inner_text()
    page.screenshot(path=str(SCREENS / "readiness_test_clock.png"))
