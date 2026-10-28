"""13c in a real browser: with readiness green, a live bot is made in the New bot sheet (Live,
real money), the bot check sends its order to the demo exchange, and the card and detail show
the real fill, marked LIVE."""

import time
from datetime import timedelta

import pyotp
import pytest
from cryptography.fernet import Fernet

from app.bots import BotJob
from app.config import Settings
from app.crypto import load_secret_box
from app.db import make_engine, make_session_factory
from app.models import Bot
from app.prices.providers import make_provider
from app.prices.service import PriceService
from app.timeutil import utcnow
from tests.ui.conftest import SCREENS, Server, _api, close_walkthrough, open_window
from tests.ui.test_bots import seed
from toolchain.tester.server import SpawnedServer

KEY = Fernet.generate_key().decode()


@pytest.fixture(scope="module")
def server():
    s = SpawnedServer(extra_env={"BOT_SYNC_DEMO": "true", "BOT_SECRET_KEY": KEY})
    s.start()
    srv = Server(s)
    srv.api("POST", "/api/setup", {"token": s.setup_token, "password": s.password})
    cookie = srv.admin_cookie()
    _, _, setup = _api(s, "POST", "/api/auth/totp/setup", None, cookie)
    srv.secret = setup["secret"]
    body = {"code": pyotp.TOTP(srv.secret).now(), "password": s.password}
    _, _, enabled = _api(s, "POST", "/api/auth/totp/enable", body, cookie)
    srv.recovery = list(enabled["recovery_codes"])
    srv.cookie = cookie  # signed in before 2FA was on: still valid (a new one would need a code)
    yield srv
    s.stop()


def sign_in_2fa(page, srv):
    page.goto(srv.base_url + "/")
    page.wait_for_selector("#login-username")
    page.fill("#login-username", "super")
    page.fill("#login-password", srv.password)
    page.click("button[type=submit]")
    page.get_by_role("button", name="Use a recovery code").click()
    page.fill("#login-code", srv.recovery.pop())
    page.get_by_role("button", name="Verify").click()
    page.wait_for_selector("body[data-session=ready]")
    close_walkthrough(page)


def make_ready(server, cookie):
    """Live trading switched on for the demo exchange, a trading key, and readiness green: a
    paper bot with 15 clean days, a drill, the limits self-check."""
    server.api("PUT", "/api/services/live", {"exchange": "demo", "on": True}, cookie)
    server.api(
        "POST",
        "/api/trading/keys",
        {
            "kind": "demo",
            "label": "Demo trading",
            "credentials": {"key": "demo-key-4321", "secret": "x"},
        },
        cookie,
    )
    plan = {"strategy": "dca", "coins": {"BTC": "100"}, "currency": "usd", "initial": "100"}
    _, _, proof = server.api("POST", "/api/bots", {"name": "Paper proof", "params": plan}, cookie)
    server.api("POST", "/api/bots/drill", {"reason": "drill"}, cookie)
    server.api("POST", "/api/bots/rearm", {"confirm": "REARM"}, cookie)
    server.api("POST", f"/api/bots/{proof['id']}/start", None, cookie)
    server.api("POST", "/api/bots/selfcheck", None, cookie)
    engine = make_engine(f"sqlite:///{server.s.tmp.name}/tester.db")
    with make_session_factory(engine)() as db:
        b = db.get(Bot, proof["id"])
        b.state = {
            **b.state,
            "clean_since": (utcnow() - timedelta(days=15)).isoformat(),
            "last_tick_at": utcnow().isoformat(),
        }
        db.commit()
    engine.dispose()
    _, _, r = server.api("GET", "/api/bots/readiness", None, cookie)
    assert r["live_allowed"], r


def test_a_live_bot_from_the_window(server, page):
    seed(server)
    make_ready(server, server.cookie)
    sign_in_2fa(page, server)
    open_window(page, "bots")
    w = page.locator(".window[data-panel=bots]")
    w.locator("[data-action=new-bot]").click()
    sheet = page.locator(".sheet")
    sheet.locator("[name=bot_name]").fill("Live BTC")
    sheet.locator("[aria-label=Mode] button:has-text('Live')").click()
    sheet.locator(".live-choice", has_text="Real money").wait_for()
    sheet.locator("[name=initial]").fill("100")
    sheet.locator("[name=every]").select_option("none")
    page.screenshot(path=str(SCREENS / "live_bot_new.png"))
    sheet.locator("[data-action=create-bot]").click()
    w.locator("[data-role=live-notice]", has_text="LIVE: real money").wait_for()

    # The bot check (run here: the test server has no background jobs) sends the order.
    engine = make_engine(f"sqlite:///{server.s.tmp.name}/tester.db")
    job = BotJob(
        PriceService(make_provider(Settings(price_provider="mock")), 60),
        make_session_factory(engine),
    )
    job.secret_box = load_secret_box(Settings(secret_key=KEY, _env_file=None))
    job.settings = Settings(sync_demo=True, _env_file=None)
    out = job.tick()
    engine.dispose()
    assert out["live"]["sent"] == 1 and out["filled"] >= 1, out
    time.sleep(0.5)
    w.locator("[data-action=all-bots]").click()
    card = w.locator(".bot-card.live", has_text="Live BTC")
    card.locator(".badge.live-badge", has_text="LIVE").wait_for()
    card.locator(".big").wait_for()
    page.screenshot(path=str(SCREENS / "live_bot_card.png"))
    card.locator("[data-action=open-bot]").click()
    w.locator("td", has_text="filled").first.wait_for()
    page.screenshot(path=str(SCREENS / "live_bot_detail.png"))
