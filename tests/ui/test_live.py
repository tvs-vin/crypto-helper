"""12b in a real browser, two people at once: a change made by one shows up in the other's
windows without a reload; an admin opens a window on the other's desktop; taking a permission
away closes the window it fed and updates the Windows menu at once."""

from tests.ui.conftest import SCREENS, open_window, sign_in


def launcher_items(pg):
    pg.click("[data-action=launcher]")
    items = pg.locator(".menu-item[data-panel]").evaluate_all(
        "els => els.map(e => e.dataset.panel)"
    )
    pg.keyboard.press("Escape")
    return items


def test_two_people_see_each_others_changes(page, server, chromium):
    pw = server.make_user("liveviewer_ui", ["wallets.view", "prices.view"])
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800})
    other = ctx.new_page()
    other.on("pageerror", lambda e: page.problems.append(f"viewer pageerror: {e}"))
    sign_in(other, server.base_url, "liveviewer_ui", pw)
    open_window(other, "wallets")
    viewer_wallets = other.locator(".window[data-panel=wallets]")
    viewer_wallets.locator(".empty, .wallet-grid").first.wait_for()

    # 1. super adds a wallet in their own browser: the viewer's Wallets window shows it.
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "wallets")
    page.click("[data-action=new-wallet]")
    sheet = page.locator(".window[data-panel=wallets] .sheet")
    sheet.locator("[name=name]").fill("Pushed live")
    sheet.locator("button[type=submit]").click()
    viewer_wallets.locator(".wallet-card", has_text="Pushed live").wait_for(timeout=10000)
    assert "wallets" in other.evaluate("() => document.body.dataset.lastTopics")

    # 2. super sees the viewer online and opens Alerts on their desktop.
    open_window(page, "users")
    row = page.locator(".window[data-panel=users] tbody tr", has_text="liveviewer_ui")
    row.locator(".badge", has_text="online").wait_for()
    row.locator("[data-action=user-menu]").click()
    page.click(".menu-item[data-action=open-window]")
    s = page.locator(".window[data-panel=users] .sheet")
    s.locator("[name=panel]").select_option("alerts")
    s.locator("[data-action=send-window]").click()
    other.locator(".window[data-panel=alerts]").wait_for(timeout=10000)
    other.locator(".toast", has_text="super opened Alerts for you").wait_for()
    other.screenshot(path=str(SCREENS / "live_opened_for_you.png"))

    # 3. super takes wallets.view away: the viewer's Wallets window closes, the menu follows.
    row.locator("[data-action=user-menu]").click()
    page.click(".menu-item[data-action=edit]")
    perms = page.locator(".window[data-panel=users] .sheet")
    perms.locator("input[value='wallets.view']").uncheck()
    perms.locator("[data-action=save-user]").click()
    viewer_wallets.wait_for(state="detached", timeout=10000)
    other.locator(".toast", has_text="Your access changed").wait_for()
    assert "Closed: Wallets" in other.locator(".toast", has_text="Your access changed").inner_text()
    assert "wallets" not in launcher_items(other)
    other.screenshot(path=str(SCREENS / "live_access_changed.png"))
    ctx.close()
