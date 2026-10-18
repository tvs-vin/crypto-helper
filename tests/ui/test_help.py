"""10a in a real browser: the Help window (the wiki, inside the app)."""

from tests.ui.conftest import open_window, sign_in


def test_help_window(page, server):
    pw = server.make_user("help_ui", [])  # anyone signed in, no permissions needed
    sign_in(page, server.base_url, "help_ui", pw)
    open_window(page, "help")
    w = page.locator(".window[data-panel=help]")
    w.locator(".help-page h2", has_text="Crypto Helper").first.wait_for()
    # The contents, by section; open a guide.
    w.locator(".help-nav-item[data-page='guides/notifications']").click()
    w.locator(".help-page h2", has_text="Notifications").wait_for()
    assert w.locator(".help-nav-item.active").inner_text() == "Notifications"
    # Wiki links open inside Help, at the right heading.
    w.locator(".help-page a.help-link[data-page='guides/prices-and-portfolio']").first.click()
    w.locator(".help-page h3[data-anchor=price-alerts]").wait_for()
    page.wait_for_function(  # scrolled to the top of the page area
        """() => {
          const h = document.querySelector('.window[data-panel=help] [data-anchor=price-alerts]');
          const box = h.closest('.help-page').getBoundingClientRect();
          const r = h.getBoundingClientRect();
          return r.top >= box.top - 2 && r.top < box.top + 80;
        }"""
    )
    w.locator("[data-action=help-back]").click()
    w.locator(".help-page h2", has_text="Notifications").wait_for()
    # Tables, code and quotes render as elements, never as raw markup.
    w.locator(".help-nav-item[data-page='guides/getting-started']").click()
    w.locator(".help-page blockquote").first.wait_for()
    w.locator(".help-page pre.help-code").first.wait_for()
    assert "**" not in w.locator(".help-page").inner_text()
    assert "{{" not in w.locator(".help-page").inner_text()
    # Search.
    w.locator("[name=help_search]").fill("discord webhook")
    w.locator(".help-hit[data-page='guides/notifications']").click()
    w.locator(".help-page h3[data-anchor]").first.wait_for()
    page.screenshot(path="tests/ui/screens/help_window.png")
    # Outside links open elsewhere, safely.
    w.locator("[name=help_search]").fill("")
    w.locator(".help-nav-item[data-page='guides/prices-and-portfolio']").click()
    ext = w.locator(".help-page a[target=_blank]").first
    ext.wait_for()
    assert ext.get_attribute("rel") == "noopener noreferrer"


def test_window_help_buttons(page, server):
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "overview")
    page.locator(".window[data-panel=overview] [data-action=window-help]").click()
    w = page.locator(".window[data-panel=help]")
    w.locator(".help-page h2", has_text="Prices and portfolio").wait_for()
    # With Help already open, another window's "?" turns it to that window's page and heading.
    open_window(page, "audit")
    page.locator(".window[data-panel=audit] [data-action=window-help]").click()
    w.locator(".help-page h3[data-anchor=audit-log]").wait_for()
    assert page.locator(".window[data-panel=help]").count() == 1
