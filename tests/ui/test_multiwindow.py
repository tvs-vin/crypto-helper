"""Several windows of one app (Overview is the main case), each with its own state."""

from tests.ui.conftest import open_window, sign_in, wait_saved


def new_window(pg, panel):
    pg.click("[data-action=launcher]")
    pg.click(f".menu-plus[data-new-window={panel}]")


def win(pg, wid):
    return pg.locator(f".window[data-window='{wid}']")


def test_two_overviews_keep_their_own_currency_and_chart(page, server):
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "overview")
    new_window(page, "overview")
    second = win(page, "overview:2")
    second.wait_for()
    assert second.locator(".title").inner_text() == "Overview 2"
    assert page.locator(".task[data-panel=overview]").count() == 2
    with page.expect_response(lambda r: "/api/prices?fiat=eur" in r.url):
        second.locator("[aria-label=Currency]").select_option("eur")
    second.locator("tr[data-symbol=ETH]").click()
    second.locator(".chart-head h3", has_text="ETH price").wait_for()
    wait_saved(page)
    assert win(page, "overview").locator("[aria-label=Currency]").input_value() == "usd"

    page.reload()
    page.wait_for_selector("body[data-session=ready]")
    first, second = win(page, "overview"), win(page, "overview:2")
    second.locator(".chart-head h3", has_text="ETH price").wait_for()  # chart came back
    assert second.locator("[aria-label=Currency]").input_value() == "eur"
    assert first.locator("[aria-label=Currency]").input_value() == "usd"
    assert first.locator(".coin-chart .chart-head").count() == 0  # no coin picked there
    page.screenshot(path="tests/ui/screens/two_overviews.png")


def test_limits_and_single_window_apps(page, server):
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "audit")
    for n in (2, 3, 4):
        new_window(page, "audit")
        win(page, f"audit:{n}").wait_for()
    page.click("[data-action=launcher]")
    assert page.locator(".menu-plus[data-new-window=audit]").count() == 0  # at the limit
    assert page.locator(".menu-item[data-panel=audit] .hint").inner_text() == "4 open"
    assert page.locator(".menu-plus[data-new-window=settings]").count() == 0  # one only
    page.keyboard.press("Escape")
    win(page, "audit:4").locator(".titlebar").click()
    page.keyboard.press("Control+Alt+N")
    page.locator(".toast", has_text="At most 4 Audit log windows").wait_for()
    # Closing one frees its number for the next.
    win(page, "audit:2").locator(".win-btn.close").click()
    new_window(page, "audit")
    win(page, "audit:2").wait_for()
    assert page.locator(".window[data-panel=audit]").count() == 4


def test_ctrl_click_opens_another_and_tiling_fits_them(page, server):
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "wallets")
    page.click("[data-action=launcher]")
    page.click(".menu-item[data-panel=wallets]", modifiers=["Control"])
    win(page, "wallets:2").wait_for()
    page.keyboard.press("Control+Alt+T")  # tiled
    page.wait_for_timeout(400)
    a = win(page, "wallets").bounding_box()
    b = win(page, "wallets:2").bounding_box()
    overlap = not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                   or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])  # fmt: skip
    assert not overlap
    # The taskbar brings back the right one.
    win(page, "wallets:2").locator("[aria-label=Minimize]").click()
    page.click(".task[data-window='wallets:2']")
    assert win(page, "wallets:2").is_visible()
    page.keyboard.press("Control+Alt+T")
