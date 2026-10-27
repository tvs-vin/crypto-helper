"""13a in a real browser: super switches live trading on for the demo exchange, sets their cap
(raising it needs a 2FA code), adds trading keys (one the exchange can't vouch for is confirmed;
one that can withdraw is refused), and sets someone else's cap and ceiling in Users."""

import time

import pyotp
import pytest

from tests.ui.conftest import SCREENS, Server, _api, close_walkthrough, open_window
from toolchain.tester.server import SpawnedServer


@pytest.fixture(scope="module")
def server():
    s = SpawnedServer(extra_env={"BOT_SYNC_DEMO": "true"})
    s.start()
    srv = Server(s)
    srv.api("POST", "/api/setup", {"token": s.setup_token, "password": s.password})
    cookie = srv.admin_cookie()
    _, _, setup = _api(s, "POST", "/api/auth/totp/setup", None, cookie)
    srv.secret = setup["secret"]
    body = {"code": pyotp.TOTP(srv.secret).now(), "password": s.password}
    _, _, enabled = _api(s, "POST", "/api/auth/totp/enable", body, cookie)
    srv.recovery = list(enabled["recovery_codes"])  # sign-ins use these; codes stay for raises
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


def test_trading_keys_and_caps(server, page):
    sign_in_2fa(page, server)

    # 1. Services: super switches live trading on for the demo exchange.
    open_window(page, "services")
    s = page.locator(".window[data-panel=services]")
    s.locator("[data-action=live-demo][aria-checked=false]").click()
    page.locator(".toast", has_text="Live trading on Demo exchange on").wait_for()
    s.locator(".win-btn.close").click()

    # 2. Live trading: lower the cap (no code), then raise it (a code).
    open_window(page, "trading")
    w = page.locator(".window[data-panel=trading]")
    w.locator("[data-role=cap]", has_text="$150").wait_for()
    w.locator("[name=cap]").fill("120")
    w.locator("[data-action=save-cap]").click()
    w.locator("[data-role=cap]", has_text="$120").wait_for()
    w.locator("[name=cap]").fill("200")
    w.locator("[data-action=save-cap]").click()
    w.locator(".notice.error", has_text="needs a current 2FA code").wait_for()
    w.locator("[name=cap]").fill("200")
    w.locator("[name=code]").fill(pyotp.TOTP(server.secret).at(time.time() + 30))
    w.locator("[data-action=save-cap]").click()
    w.locator("[data-role=cap]", has_text="$200").wait_for()

    # 3. A key the exchange can't vouch for: confirm what was ticked.
    w.locator("[data-action=add-key]").click()
    sheet = page.locator(".sheet")
    sheet.locator("[name=key_label]").fill("Demo trading")
    sheet.locator("[name=cred_key]").fill("unknown-key-5678")
    sheet.locator("[name=cred_secret]").fill("pretend")
    sheet.locator("[data-action=save-key]").click()
    sheet.locator("[name=confirm_no_withdrawals]").wait_for()
    page.screenshot(path=str(SCREENS / "trading_confirm.png"))
    sheet.locator("[name=cred_key]").fill("unknown-key-5678")
    sheet.locator("[name=cred_secret]").fill("pretend")
    sheet.locator("[name=confirm_no_withdrawals]").check()
    sheet.locator("[data-action=save-key]").click()
    w.locator(".key-card", has_text="confirmed by super").wait_for()

    # 4. A key that can withdraw is refused.
    w.locator("[data-action=add-key]").click()
    sheet.locator("[name=key_label]").fill("Too powerful")
    sheet.locator("[name=cred_key]").fill("withdraw-key-0000")
    sheet.locator("[name=cred_secret]").fill("pretend")
    sheet.locator("[data-action=save-key]").click()
    sheet.locator(".notice.error", has_text="can withdraw").wait_for()
    sheet.locator("button", has_text="Cancel").click()
    assert w.locator(".key-card").count() == 1
    page.screenshot(path=str(SCREENS / "trading_window.png"))

    # 5. Users: someone else's cap and ceiling (lowering the cap needs no code).
    page.evaluate("""() => fetch('/api/users', {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'},
        body: JSON.stringify({username: 'capped_ui', password: 'ui-test-passphrase',
                              permissions: ['live.trade']})})""")
    open_window(page, "users")
    u = page.locator(".window[data-panel=users]")
    u.locator("[data-action=user-menu][data-user=capped_ui]").click()
    page.locator(".menu-item[data-action=trading-cap]").click()
    page.locator(".sheet [name=cap]").fill("75")
    page.locator(".sheet [name=ceiling]").fill("100")
    page.locator(".sheet [data-action=save-trading-cap]").click()
    page.locator(".toast", has_text="capped_ui").wait_for()
