"""7a in a real browser: the App manager, and what accounts see after their apps change."""

from tests.ui.conftest import open_window, sign_in


def launcher_items(pg):
    pg.click("[data-action=launcher]")
    items = pg.locator(".menu-item[data-panel]").evaluate_all(
        "els => els.map(e => e.dataset.panel)"
    )
    pg.keyboard.press("Escape")
    return items


def cell(pg, account, app):
    return pg.locator(f".apps-grid tr[data-account={account}] input[data-app={app}]")


def test_switch_an_app_off_for_one_account(page, server, chromium):
    pw = server.make_user("appviewer_ui", ["wallets.view", "prices.view"])
    # The viewer has a Wallets window open from before.
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800})
    other = ctx.new_page()
    sign_in(other, server.base_url, "appviewer_ui", pw)
    open_window(other, "wallets")
    other.wait_for_timeout(900)  # layout save is debounced
    assert "wallets" in launcher_items(other)

    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "apps")
    box = cell(page, "appviewer_ui", "wallets")
    box.wait_for()
    assert cell(page, "super", "wallets").is_disabled()  # super always has everything
    box.uncheck()
    page.locator(".toast", has_text="Wallets off for appviewer_ui").wait_for()
    page.screenshot(path="tests/ui/screens/app_manager.png")

    other.reload()
    other.wait_for_selector("body[data-session=ready]")
    assert "wallets" not in launcher_items(other)
    assert other.locator(".window[data-panel=wallets]").count() == 0  # not restored either
    ctx.close()


def test_switch_an_app_off_for_everyone(page, server, chromium):
    pw = server.make_user("appeveryone_ui", ["wallets.view", "prices.view"])
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "apps")
    page.locator("[data-action=switch-overview]").click()
    page.locator(".toast", has_text="Overview turned off for everyone").wait_for()
    page.locator("[data-action=switch-overview][aria-checked=false]").wait_for()
    assert "overview" in launcher_items(page)  # super keeps it

    ctx = chromium.new_context()
    other = ctx.new_page()
    sign_in(other, server.base_url, "appeveryone_ui", pw)
    assert "overview" not in launcher_items(other)
    ctx.close()
    page.locator("[data-action=switch-overview]").click()
    page.locator("[data-action=switch-overview][aria-checked=true]").wait_for()


def test_a_manager_only_switches_apps_they_can_use(page, server):
    pw = server.make_user("appmgr_ui", ["apps.manage", "wallets.view"])
    server.make_user("appplain_ui", ["wallets.view"])
    sign_in(page, server.base_url, "appmgr_ui", pw)
    open_window(page, "apps")
    cell(page, "appplain_ui", "wallets").wait_for()
    assert not cell(page, "appplain_ui", "wallets").is_disabled()
    assert cell(page, "appplain_ui", "audit").is_disabled()  # appmgr_ui can't use Audit
    assert cell(page, "appmgr_ui", "wallets").is_disabled()  # not yourself
    assert page.locator("[data-action=switch-audit]").is_disabled()
    # On but missing a permission: marked, with the reason on hover.
    note = page.locator(".apps-grid tr[data-account=appplain_ui] td .cell-note").first
    assert "needs" in note.get_attribute("title")


def test_no_app_manager_without_the_permission(page, server):
    pw = server.make_user("noapps_ui", ["wallets.view"])
    sign_in(page, server.base_url, "noapps_ui", pw)
    items = launcher_items(page)
    assert "apps" not in items and "settings" in items
