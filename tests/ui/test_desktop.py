import time

import pyotp

from tests.ui.conftest import box, open_window, sign_in, wait_saved

# ---- the sign-in flow --------------------------------------------------------------------


def test_first_launch_setup_then_sign_in(fresh_server, page):  # server outlives the browser
    page.goto(fresh_server.base_url + "/")
    page.wait_for_selector("#setup-token")
    assert page.locator(".overlay").is_visible() and page.locator(".taskbar").count() == 1
    page.fill("#setup-token", fresh_server.setup_token)
    page.fill("#setup-password", fresh_server.password)
    page.fill("#setup-password2", fresh_server.password)
    page.click("button[type=submit]")
    page.wait_for_selector("#login-password")
    assert page.input_value("#login-username") == "super"
    page.fill("#login-password", fresh_server.password)
    page.click("button[type=submit]")
    page.wait_for_selector("body[data-session=ready]")
    assert page.locator(".overlay").count() == 0  # the box closed on the same page
    assert page.locator(".toast", has_text="two-factor").count() == 1


def test_setup_mismatched_passwords(page, fresh_server):
    page.goto(fresh_server.base_url + "/")
    page.wait_for_selector("#setup-token")
    page.fill("#setup-token", fresh_server.setup_token)
    page.fill("#setup-password", "one-long-password")
    page.fill("#setup-password2", "another-long-password")
    page.click("button[type=submit]")
    assert "don't match" in page.inner_text(".notice.error")


def test_wrong_password_shows_error_and_keeps_the_box(page, server):
    page.goto(server.base_url + "/")
    page.wait_for_selector("#login-username")
    page.fill("#login-username", "super")
    page.fill("#login-password", "not-the-password")
    page.click("button[type=submit]")
    page.wait_for_selector(".notice.error")
    assert "Invalid username or password" in page.inner_text(".notice.error")
    assert page.input_value("#login-password") == ""
    assert page.locator(".overlay").is_visible()


def test_two_factor_and_recovery_code(page, server):
    pw = server.make_user("twofa_ui", ["wallets.view"])
    _, headers, _ = server.api("POST", "/api/auth/login", {"username": "twofa_ui", "password": pw})
    cookie = headers["set-cookie"].split(";")[0]
    secret = server.api("POST", "/api/auth/totp/setup", {}, cookie)[2]["secret"]
    codes = server.api("POST", "/api/auth/totp/enable", {"code": pyotp.TOTP(secret).now()}, cookie)[
        2
    ]["recovery_codes"]

    page.goto(server.base_url + "/")
    page.wait_for_selector("#login-username")
    page.fill("#login-username", "twofa_ui")
    page.fill("#login-password", pw)
    page.click("button[type=submit]")
    page.wait_for_selector("#login-code")
    assert "authenticator" in page.inner_text(".auth-head")
    page.click("text=Use a recovery code")
    page.fill("#login-code", codes[0])
    page.click("button[type=submit]")
    page.wait_for_selector("body[data-session=ready]")
    assert page.locator(".overlay").count() == 0


def test_permissions_decide_which_windows_can_open(page, server):
    pw = server.make_user("viewer_ui", ["wallets.view"])
    sign_in(page, server.base_url, "viewer_ui", pw)
    page.click("[data-action=launcher]")
    panels = page.locator(".menu-item[data-panel]").evaluate_all(
        "els => els.map(e => e.dataset.panel)"
    )
    assert panels == ["wallets", "transfers", "notifications", "help", "settings"]


# ---- windows -----------------------------------------------------------------------------


def test_drag_snap_and_layout_survives_signing_in_again(page, server, chromium):
    pw = server.make_user("layout_ui", ["wallets.view", "prices.view"])
    sign_in(page, server.base_url, "layout_ui", pw)
    open_window(page, "wallets")
    open_window(page, "settings")
    # Drag Wallets by its titlebar to the left edge: it snaps to the left half.
    title = page.locator(".window[data-panel=wallets] .titlebar .title").bounding_box()
    page.mouse.move(title["x"] + 40, title["y"] + 10)
    page.mouse.down()
    page.mouse.move(400, 300, steps=8)
    page.mouse.move(2, 400, steps=8)
    assert page.locator(".snap-preview").is_visible()
    page.mouse.up()
    time.sleep(0.3)
    snapped = box(page, "wallets")
    assert abs(snapped["x"] - 8) <= 2 and abs(snapped["width"] - (1440 - 24) / 2) <= 3
    wait_saved(page)

    # A brand-new browser session: the same windows come back where they were.
    context = chromium.new_context(viewport={"width": 1440, "height": 900})
    again = context.new_page()
    sign_in(again, server.base_url, "layout_ui", pw)
    time.sleep(0.2)
    assert sorted(again.locator(".window").evaluate_all("e => e.map(w => w.dataset.panel)")) == [
        "settings",
        "wallets",
    ]
    restored = box(again, "wallets")
    assert abs(restored["x"] - snapped["x"]) <= 2 and abs(restored["width"] - snapped["width"]) <= 2
    context.close()


def test_tiled_mode_never_overlaps_and_is_remembered(page, server):
    pw = server.make_user("tiled_ui", ["wallets.view", "prices.view", "audit.view"])
    sign_in(page, server.base_url, "tiled_ui", pw)
    for panel in ("wallets", "overview", "settings"):
        open_window(page, panel)
    page.click(".mode-toggle")
    wait_saved(page)
    time.sleep(0.3)
    rects = [box(page, p) for p in ("wallets", "overview", "settings")]
    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            assert (
                a["x"] + a["width"] <= b["x"] + 1
                or b["x"] + b["width"] <= a["x"] + 1
                or a["y"] + a["height"] <= b["y"] + 1
                or b["y"] + b["height"] <= a["y"] + 1
            )
    page.reload()
    page.wait_for_selector("body[data-session=ready]")
    assert "layout-tiled" in page.get_attribute("#desktop", "class")
    assert "Tiled" in page.inner_text(".mode-toggle")


def test_keyboard_snap_minimize_and_taskbar(page, server):
    pw = server.make_user("keys_ui", ["wallets.view"])
    sign_in(page, server.base_url, "keys_ui", pw)
    open_window(page, "wallets")
    page.keyboard.press("Control+Alt+ArrowRight")
    time.sleep(0.3)
    b = box(page, "wallets")
    assert b["x"] > 700 and abs(b["width"] - (1440 - 24) / 2) <= 3
    page.keyboard.press("Control+Alt+ArrowDown")
    assert not page.locator(".window[data-panel=wallets]").is_visible()
    page.click(".task[data-panel=wallets]")  # the taskbar brings it back
    assert page.locator(".window[data-panel=wallets]").is_visible()


def test_close_and_maximize(page, server):
    pw = server.make_user("max_ui", ["wallets.view"])
    sign_in(page, server.base_url, "max_ui", pw)
    open_window(page, "wallets")
    page.dblclick(".window[data-panel=wallets] .titlebar .title")
    time.sleep(0.3)
    b = box(page, "wallets")
    assert b["width"] > 1400 and b["x"] <= 10
    page.click(".window[data-panel=wallets] .win-btn.close")
    assert page.locator(".window").count() == 0 and page.locator(".desktop-empty").is_visible()


# ---- themes ------------------------------------------------------------------------------


def accent(pg):
    return pg.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--c-accent')"
    ).strip()


def test_theme_applies_at_once_and_follows_the_user(page, server, chromium):
    pw = server.make_user("theme_ui", [])
    sign_in(page, server.base_url, "theme_ui", pw)
    assert accent(page).lower() == "#7545fc"
    open_window(page, "settings")
    page.click(".settings-nav [data-section=appearance]")  # themes live here
    with page.expect_response(lambda r: r.url.endswith("/api/me/preferences")):
        page.click(".theme-card[data-theme=terminal]")
    assert accent(page).lower() == "#3be36a"
    assert page.evaluate("document.documentElement.dataset.density") == "compact"
    context = chromium.new_context(viewport={"width": 1440, "height": 900})
    other = context.new_page()  # another device: no cached theme until sign-in
    sign_in(other, server.base_url, "theme_ui", pw)
    assert accent(other).lower() == "#3be36a"
    context.close()


# ---- the session ending mid-use ----------------------------------------------------------


def test_expired_session_brings_the_box_back_over_the_same_windows(page, server):
    pw = server.make_user("expiry_ui", [])
    sign_in(page, server.base_url, "expiry_ui", pw)
    open_window(page, "settings")
    page.click(".settings-nav [data-section=appearance]")  # themes live here
    # The cards are drawn only after the section's own request returns. Ending the session
    # before that made this test flaky under load (that request got the 401 instead).
    page.wait_for_selector(".theme-card[data-theme=light]")
    before = box(page, "settings")
    page.context.clear_cookies()  # the session ends (as after 12 hours or a sign-out elsewhere)
    page.click(".theme-card[data-theme=light]")
    page.wait_for_selector("#login-password")
    assert "session ended" in page.inner_text(".auth-head")
    assert page.input_value("#login-username") == "expiry_ui"
    assert page.locator(".window[data-panel=settings]").count() == 1  # still there behind
    page.fill("#login-password", pw)
    page.click("button[type=submit]")
    page.wait_for_selector(".overlay", state="detached")
    time.sleep(0.3)
    assert box(page, "settings") == before
    assert accent(page).lower() == "#6234e8"  # the click that hit the expiry went through


def test_sign_out_and_in(page, server):
    """Regressions: a layout save still pending at sign-out opened a second sign-in box;
    the first fix then dropped that save, losing the last change. It must be kept."""
    pw = server.make_user("signout_ui", [])
    sign_in(page, server.base_url, "signout_ui", pw)
    open_window(page, "settings")
    page.click(".user-chip")
    page.click("[data-action=logout]")
    page.wait_for_selector("#login-username")
    assert page.locator(".window").count() == 0
    page.fill("#login-username", "signout_ui")
    page.fill("#login-password", pw)
    page.click("button[type=submit]")
    page.wait_for_selector("body[data-session=ready]")
    page.wait_for_selector(".window[data-panel=settings]")


# ---- small screens -----------------------------------------------------------------------


def test_narrow_screen_stacks_windows(page, server):
    pw = server.make_user("narrow_ui", ["wallets.view"])
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page, server.base_url, "narrow_ui", pw)
    open_window(page, "wallets")
    open_window(page, "settings")
    assert (
        page.evaluate("getComputedStyle(document.querySelector('.window')).position") == "relative"
    )
    a, b = box(page, "wallets"), box(page, "settings")
    assert a["width"] <= 390 and b["y"] >= a["y"] + a["height"] - 1
    assert page.evaluate("document.documentElement.scrollWidth") <= 390  # no sideways scroll


def test_browser_refuses_a_malicious_theme_too(page, server):
    """Defence in depth: theme.js re-checks every value before it becomes a CSS variable."""
    pw = server.make_user("evil_theme_ui", [])
    sign_in(page, server.base_url, "evil_theme_ui", pw)
    result = page.evaluate("""async () => {
        const m = await import('/static/js/theme.js');
        const good = await m.loadBuiltin('dark');
        const tries = {
          url: {...good, colors: {...good.colors, accent: 'url(https://evil.example/x)'}},
          css: {...good, colors: {...good.colors, surface: 'red; background: url(x)'}},
          font: {...good, fonts: {...good.fonts, body: 'Comic Sans", url(x)'}},
        };
        const out = {};
        for (const [k, t] of Object.entries(tries)) {
          try { m.applyTheme(t); out[k] = 'applied'; } catch { out[k] = 'refused'; }
        }
        const root = getComputedStyle(document.documentElement);
        out.accent = root.getPropertyValue('--c-accent').trim();
        return out;
    }""")
    assert result == {"url": "refused", "css": "refused", "font": "refused", "accent": "#7545FC"}


def test_reloading_right_after_a_change_keeps_it(page, server):
    """Regression: a layout change inside the 0.6 s save delay was lost on reload. It's now
    sent as the page goes away."""
    pw = server.make_user("reload_ui", ["wallets.view"])
    sign_in(page, server.base_url, "reload_ui", pw)
    open_window(page, "wallets")
    page.reload()  # immediately, inside the debounce window
    page.wait_for_selector("body[data-session=ready]")
    page.wait_for_selector(".window[data-panel=wallets]")
