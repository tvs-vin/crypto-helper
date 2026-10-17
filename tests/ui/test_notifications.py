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
    bob.locator("[data-category=messages][data-channel=inapp]").uncheck()
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


def test_discord_webhook_and_quiet_hours(page, server):
    """9b: add a webhook (only the masked label comes back), tick Discord, set quiet hours."""
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "settings")
    page.click(".settings-nav [data-section=notifications]")
    w = page.locator(".window[data-panel=settings]")
    w.locator("[name=webhook]").fill("https://evil.example/api/webhooks/1/x")
    w.locator("[data-action=discord-save]").click()
    w.locator(".notice.error", has_text="isn't a Discord webhook").wait_for()
    token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-wxyz"
    w.locator("[name=webhook]").fill(f"https://discord.com/api/webhooks/123456789012345678/{token}")
    w.locator("[data-action=discord-save]").click()
    w.locator("text=Discord webhook …5678 (token …wxyz)").wait_for()
    assert token not in w.inner_text()
    w.locator("[data-category=system][data-channel=discord]").check()
    page.locator(".toast", has_text="System on Discord: on").wait_for()
    w.locator("[name=quiet_from]").fill("22:00")
    w.locator("[name=quiet_to]").fill("07:00")
    page.locator(".toast", has_text="Quiet 22:00–07:00").wait_for()
    prefs = server.api("GET", "/api/me/preferences", cookie=server.admin_cookie())[2]
    n = prefs["notifications"]
    assert n["channels"]["system"]["discord"] and n["quiet_to"] == "07:00"
    assert "utc_offset_minutes" in n
    page.screenshot(path="tests/ui/screens/notification_settings.png")
    w.locator("[data-action=discord-remove]").click()
    w.locator("[name=webhook]").wait_for()


def test_a_lockout_pops_up_for_the_admin(page, server):
    """9c: an automatic security notification arrives live while the admin is signed in."""
    server.make_user("lock_ui", ["wallets.view"])
    sign_in(page, server.base_url, "super", server.password)
    page.wait_for_timeout(500)  # the live stream is open
    import urllib.error

    for i in range(5):
        try:
            server.api("POST", "/api/auth/login", {"username": "lock_ui", "password": f"wrong-{i}"})
        except urllib.error.HTTPError as e:
            assert e.code == 401
    toast = page.locator(".toast", has_text="lock_ui was locked out")
    toast.wait_for(timeout=10000)
    page.screenshot(path="tests/ui/screens/notification_lockout.png")
    page.locator("[data-action=bell]").click()
    item = page.locator(".notification", has_text="lock_ui was locked out")
    item.wait_for()
    assert "Security" in item.inner_text()
