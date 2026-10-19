"""12a in a real browser: first launch to a set-up server. super creates the account, must turn
on 2FA before anything else, walks through the server setup (an account invited there), then the
app; the Getting started window ticks itself. The invited person must choose their own password
at first sign-in and gets only the steps their permissions allow."""

import pyotp
import pytest

from tests.ui.conftest import SCREENS
from toolchain.tester.server import SpawnedServer

PW = "first-launch-passphrase-1"
ALICE_PW = "given-by-super-123"


@pytest.fixture
def first_launch():
    # As installed: super must turn on two-factor login.
    s = SpawnedServer(extra_env={"BOT_SUPER_REQUIRES_TWO_FACTOR": "true"})
    s.start()
    yield s
    s.stop()


def wizard(page):
    return page.locator(".wizard")


def step_title(page):
    return page.locator("#wizard-title").inner_text()


def wait_title(page, text):
    page.wait_for_function(
        "(t) => document.querySelector('#wizard-title')?.innerText === t", arg=text
    )


def next_step(page, expect=None):
    page.click("[data-action=wizard-next]")
    if expect:
        page.wait_for_function(
            "(t) => document.querySelector('#wizard-title')?.innerText === t", arg=expect
        )


def test_first_launch_to_a_set_up_server(first_launch, page):  # server outlives the browser
    s = first_launch
    page.goto(s.base_url + "/")
    # 1. The setup screen explains the token and rates the password.
    page.wait_for_selector("#setup-token")
    assert (
        page.locator(".auth-card .copyable input").input_value() == "sudo crypto-helper setup token"
    )
    page.fill("#setup-password", "short")
    assert "Too short" in page.locator(".strength").inner_text()
    page.fill("#setup-token", s.setup_token)
    page.fill("#setup-password", PW)
    assert page.locator(".strength").inner_text() == "Strong"
    page.fill("#setup-password2", PW)
    page.screenshot(path=str(SCREENS / "onboarding_setup.png"))
    page.click("button[type=submit]")
    page.wait_for_selector("#login-password")
    page.fill("#login-password", PW)
    page.click("button[type=submit]")

    # 2. Rules first: super can't do anything before turning on 2FA (no way to skip or hide).
    page.wait_for_selector("body[data-walkthrough=rules]")
    wait_title(page, "Turn on two-factor login")
    assert page.locator("[data-action=wizard-skip]").is_hidden()
    assert page.locator("[data-action=wizard-hide]").count() == 0
    assert page.locator("[data-action=wizard-next]").is_disabled()
    page.click("[data-action=wizard-2fa]")
    secret = page.locator(".wizard .qr-row .copyable input").input_value()
    page.fill("[aria-label='Code from the app']", pyotp.TOTP(secret).now())
    page.fill(".wizard input[name=current_password]", PW)
    page.click("[data-action=confirm-2fa]")
    page.click("[data-action=codes-saved]")
    page.wait_for_selector(".wizard .badge.ok")
    page.click("[data-action=wizard-next]")  # "Continue"

    # 3. The walkthrough: the server first.
    page.wait_for_selector("body[data-walkthrough=open]")
    page.wait_for_selector("body[data-session=ready]")
    wait_title(page, "What Crypto Helper does, and never does")
    nav = page.locator(".wizard-nav").inner_text().lower()
    assert "your server" in nav and "getting to know it" in nav
    assert "never does" in wizard(page).inner_text()
    page.screenshot(path=str(SCREENS / "onboarding_welcome.png"))
    next_step(page, "Turn on two-factor login")  # already done: ticked
    assert "Two-factor login is on" in wizard(page).inner_text()
    next_step(page, "Back up the encryption key")
    assert page.locator("[data-action=wizard-next]").is_disabled()
    page.check("input[name=key_saved]")
    next_step(page, "Where it listens, who may connect")
    page.wait_for_selector(".wizard .net-row")
    text = wizard(page).inner_text()
    assert "127.0.0.1" in text and "this machine only" in text
    assert "needs the agent" in text  # a throwaway server has no agent: the manual way
    assert "BOT_HOST=127.0.0.1" in page.locator(".wizard textarea").input_value()
    page.screenshot(path=str(SCREENS / "onboarding_network.png"))
    next_step(page, "Services and features")
    page.wait_for_selector(".wizard .features")
    next_step(page, "Prices, history and syncing")
    page.wait_for_selector(".wizard [name=sync_every]")
    next_step(page, "Invite people")
    # Users, right here: invite alice (viewer), who must choose her own password.
    page.click(".wizard [data-action=new-user]")
    sheet = page.locator(".wizard .sheet")
    sheet.locator("[name=username]").fill("alice")
    sheet.locator("[name=password]").fill(ALICE_PW)
    assert sheet.locator("[name=must_change_password]").is_checked()  # the default
    sheet.locator("[aria-label=Preset]").select_option("viewer")
    sheet.locator("[data-action=save-user]").click()
    page.locator(".wizard tbody tr", has_text="alice").wait_for()
    assert "new password due" in page.locator(".wizard tbody tr", has_text="alice").inner_text()

    # 4. Then the app.
    next_step(page, "Currency, theme and size")
    page.click(".wizard [aria-label=Theme] button:has-text('Light')")
    page.wait_for_function("() => document.documentElement.dataset.mode === 'light'")
    next_step(page, "Coins to watch")
    page.click(".wizard [data-coin=BTC]")
    page.wait_for_selector(".wizard-nav li.done [data-step=watchlist]")
    next_step(page, "Add your first wallet")
    page.fill("[name=paper_name]", "Practice")
    page.click("[data-action=wizard-paper]")
    page.wait_for_selector(".wizard-nav li.done [data-step=wallets]")
    page.screenshot(path=str(SCREENS / "onboarding_wallets.png"))
    next_step(page, "Sync a wallet from an exchange or an address")
    # "Open Wallets" shrinks the walkthrough to its bar; Continue brings it back.
    page.click(".wizard button:has-text('Open Wallets')")
    page.wait_for_selector(".window[data-panel=wallets] .wallet-card")
    page.wait_for_selector(".wizard-pill:not(.hidden)")
    page.click("[data-action=wizard-continue]")
    page.wait_for_function(
        "() => document.querySelector('#wizard-title')?.innerText.startsWith('Sync')"
    )
    next_step(page, "Set an alert")
    next_step(page, "Notifications and Discord")
    next_step(page, "A tour of the desktop")
    page.click("[data-action=wizard-tour]")
    for _ in range(6):
        page.wait_for_selector(".tour-tip")
        page.click("[data-action=tour-next]")
    page.click("[data-action=wizard-continue]")
    page.wait_for_selector(".wizard-nav li.done [data-step=tour]")
    with page.expect_response(lambda r: r.url.endswith("/api/onboarding/finish")):
        page.click("[data-action=wizard-next]")  # Finish
    page.wait_for_function("() => !document.body.dataset.walkthrough")

    # 5. Getting started: ticked from what's really set up.
    page.click("[data-action=launcher]")
    page.click(".menu-item[data-panel=start]")
    start = page.locator(".window[data-panel=start]")
    start.locator(".start-item").first.wait_for()
    steps = ("twofa", "key_backup", "network", "people", "wallets", "sync", "alerts", "tour")
    done = {
        st: "done" in (start.locator(f"[data-step={st}]").get_attribute("class") or "")
        for st in steps
    }
    assert [st for st in steps if done[st]] == [
        "twofa", "key_backup", "network", "people", "wallets", "tour",
    ]  # fmt: skip
    page.screenshot(path=str(SCREENS / "onboarding_getting_started.png"))
    start.locator("[data-step=alerts] [data-action=start-step]").click()  # back in, at that step
    page.wait_for_function(
        "() => document.querySelector('#wizard-title')?.innerText === 'Set an alert'"
    )
    page.click("[data-action=wizard-hide]")
    page.click("[data-action=wizard-close]")

    # 6. Alice's first sign-in: her own password first, then only her steps.
    page.click(".user-chip")
    page.click("[data-action=logout]")
    page.wait_for_selector("#login-username")
    page.fill("#login-username", "alice")
    page.fill("#login-password", ALICE_PW)
    page.click("button[type=submit]")
    page.wait_for_selector("body[data-walkthrough=rules]")
    wait_title(page, "Choose your own password")
    page.fill(".wizard [name=current]", ALICE_PW)
    page.fill(".wizard [name=new]", "alice-own-passphrase-2")
    page.fill(".wizard [name=repeat]", "alice-own-passphrase-2")
    page.click("[data-action=wizard-password]")
    page.wait_for_selector(".wizard .badge.ok")
    page.click("[data-action=wizard-next]")
    page.wait_for_selector("body[data-walkthrough=open]")
    steps = page.locator(".wizard-nav [data-step]").evaluate_all(
        "(els) => els.map((e) => e.dataset.step)"
    )
    assert steps == [
        "welcome",
        "password",
        "twofa",
        "personalise",
        "watchlist",
        "alerts",
        "notifications",
        "tour",
    ]
    page.wait_for_timeout(400)  # the walkthrough fades in
    page.screenshot(path=str(SCREENS / "onboarding_viewer.png"))
