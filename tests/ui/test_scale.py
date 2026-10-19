"""8a in a real browser: display scale. At 125% the desktop must still behave: windows follow
the pointer exactly, snapping fills half the screen, menus open under their buttons; the
account's scale follows you and a device override stays on that device."""

from tests.ui.conftest import close_walkthrough, open_window, sign_in

VIEW = {"width": 1440, "height": 900}


def zoom(pg):
    return pg.evaluate("() => document.documentElement.style.zoom || '1'")


def set_account_scale(pg, pct):
    open_window(pg, "settings")
    pg.click(".settings-nav [data-section=display]")
    slider = pg.locator("[data-action=scale-account]")
    slider.evaluate(
        "(el, v) => { el.value = String(v); el.dispatchEvent(new Event('input', {bubbles: true}));"
        " el.dispatchEvent(new Event('change', {bubbles: true})); }",
        pct,
    )
    pg.locator(".toast", has_text=f"Scale {pct}% for your account").wait_for()
    pg.locator(".window[data-panel=settings] [aria-label=Close]").click()


def test_windows_follow_the_pointer_at_125(page, server):
    sign_in(page, server.base_url, "super", server.password)
    set_account_scale(page, 125)
    assert zoom(page) == "1.25"
    open_window(page, "audit")
    w = page.locator(".window[data-panel=audit]")
    before = w.bounding_box()
    bar = w.locator(".titlebar").bounding_box()
    x, y = bar["x"] + 120, bar["y"] + bar["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 100, y + 60, steps=8)
    page.mouse.move(x + 200, y + 100, steps=8)
    page.mouse.up()
    after = w.bounding_box()
    assert abs(after["x"] - before["x"] - 200) <= 2 and abs(after["y"] - before["y"] - 100) <= 2
    # Snap to the left edge: exactly the left half of the screen (minus the gap).
    bar = w.locator(".titlebar").bounding_box()
    page.mouse.move(bar["x"] + 60, bar["y"] + 10)
    page.mouse.down()
    page.mouse.move(2, 400, steps=15)
    page.mouse.up()
    page.wait_for_timeout(300)
    snapped = w.bounding_box()
    assert snapped["x"] < 20 and abs(snapped["width"] - VIEW["width"] / 2) < 30
    page.screenshot(path="tests/ui/screens/scale_125.png")


def test_menus_open_under_their_buttons_at_125(page, server):
    sign_in(page, server.base_url, "super", server.password)
    set_account_scale(page, 125)
    open_window(page, "overview")
    btn = page.locator(".window[data-panel=overview] [data-action=columns]")
    btn.click()
    menu = page.locator(".menu").bounding_box()
    b = btn.bounding_box()
    assert abs(menu["y"] - (b["y"] + b["height"])) < 12  # right below, in screen pixels
    assert menu["x"] + menu["width"] <= b["x"] + b["width"] + 4  # right-aligned to it
    page.keyboard.press("Escape")
    page.click("[data-action=launcher]")  # the taskbar menu opens above, inside the screen
    m = page.locator(".menu").bounding_box()
    assert m["y"] >= 0 and m["y"] + m["height"] <= VIEW["height"]


def test_account_default_and_device_override(page, server, chromium):
    sign_in(page, server.base_url, "super", server.password)
    set_account_scale(page, 110)
    page.keyboard.press("Control+Alt+-")  # this device only
    page.locator(".toast", has_text="Scale 105%").wait_for()
    assert zoom(page) == "1.05"
    page.reload()
    page.wait_for_selector("body[data-session=ready]")
    close_walkthrough(page)
    assert zoom(page) == "1.05"  # the device keeps its own
    other = chromium.new_context(viewport=VIEW).new_page()
    sign_in(other, server.base_url, "super", server.password)
    assert zoom(other) == "1.1"  # another device gets the account's
    other.context.close()
    page.keyboard.press("Control+Alt+0")
    page.locator(".toast", has_text="Your account's scale").wait_for()
    assert zoom(page) == "1.1"
    set_account_scale(page, 100)
    assert zoom(page) == "1"
