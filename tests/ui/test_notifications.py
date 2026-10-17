"""9a in a real browser: sending a notification and watching it arrive live elsewhere."""

from tests.ui.conftest import open_window, sign_in


def bell_count(pg) -> str:
    c = pg.locator(".bell .bell-count")
    return c.inner_text() if c.count() else "0"


def test_send_and_receive_live(page, server, chromium):
    pw = server.make_user("notify_ui", ["wallets.view"])
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800})
    bob = ctx.new_page()
    sign_in(bob, server.base_url, "notify_ui", pw)
    assert bell_count(bob) == "0"

    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "notifications")
    w = page.locator(".window[data-panel=notifications]")
    w.locator("[name=to]").select_option(label="notify_ui")
    w.locator("[name=title]").fill("Backup drill tonight")
    w.locator("[name=body]").fill("The app restarts at 22:00 for a minute.")
    w.locator("[name=level]").select_option("warning")
    w.locator("[name=link]").select_option("wallets")
    w.locator("[data-action=send-notification]").click()
    page.locator(".toast", has_text="Sent").wait_for()

    # Bob: a pop-up and the bell, without reloading anything.
    bob.locator(".toast", has_text="Backup drill tonight").wait_for(timeout=10000)
    bob.wait_for_function("() => document.querySelector('.bell .bell-count')?.textContent === '1'")
    bob.screenshot(path="tests/ui/screens/notification_arrives.png")
    bob.locator("[data-action=bell]").click()
    item = bob.locator(".notification.unread", has_text="Backup drill tonight")
    item.wait_for()
    assert "from super" in item.inner_text()
    item.locator("button", has_text="Open Wallets").click()
    bob.locator(".window[data-panel=wallets]").wait_for()
    bob.wait_for_function("() => !document.querySelector('.bell .bell-count')")

    # Bob turns messages off: the next one isn't delivered.
    open_window(bob, "settings")
    bob.click(".settings-nav [data-section=notifications]")
    bob.locator("[data-category=messages]").uncheck()
    bob.locator(".toast", has_text="Messages: off").wait_for()
    w.locator("[name=title]").fill("You won't see this")
    w.locator("[data-action=send-notification]").click()
    page.locator(".toast", has_text="0 people").wait_for()
    bob.wait_for_timeout(1500)
    assert bob.locator(".toast", has_text="You won't see this").count() == 0
    ctx.close()


def test_send_to_everyone_and_no_compose_without_permission(page, server, chromium):
    pw = server.make_user("plain_ui", ["wallets.view"])
    ctx = chromium.new_context()
    other = ctx.new_page()
    sign_in(other, server.base_url, "plain_ui", pw)
    open_window(other, "notifications")
    assert other.locator("[data-action=send-notification]").count() == 0

    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "notifications")
    w = page.locator(".window[data-panel=notifications]")
    w.locator("[name=title]").fill("Hello everyone")
    w.locator("[data-action=send-notification]").click()
    other.locator(".toast", has_text="Hello everyone").wait_for(timeout=10000)
    # The open Notifications window refreshes by itself.
    other.locator(".notification", has_text="Hello everyone").wait_for()
    ctx.close()
