"""6d in a real browser: making embeds in Settings, then loading them from the embed server
(its own process and port) the way Discord and a website would."""

import http.server
import threading
import urllib.error
import urllib.request

import pytest

from tests.ui.conftest import Server, open_window, sign_in
from tests.ui.seed import seed
from tests.ui.test_settings import settings
from toolchain.tester.server import SpawnedServer


@pytest.fixture(scope="module")
def server():
    """Main server + embed server, with the demo wallets."""
    s = SpawnedServer(embed=True)
    s.start()
    srv = Server(s)
    srv.api("POST", "/api/setup", {"token": s.setup_token, "password": s.password})
    seed(s)
    yield srv
    s.stop()


def status(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def embeds(pg):
    m = settings(pg, "embeds")
    m.locator("[data-action=new-embed]").wait_for()
    return m


def create(pg, name, kind="Portfolio", origins="", theme=None):
    m = embeds(pg)
    m.locator("[data-action=new-embed]").click()
    s = pg.locator(".sheet")
    s.locator("[name=name]").fill(name)
    s.locator(".segmented button", has_text=kind).click()
    if theme:
        s.locator("[name=theme]").select_option(theme)
    if origins:
        s.locator("[name=origins]").fill(origins)
    s.locator("[data-action=save-embed]").click()
    pg.locator(".toast", has_text="Embed created").wait_for()
    card = m.locator(".embed-card", has_text=name)
    card.wait_for()
    return card


def link(card):
    return card.locator(".copyable input").first.input_value()


def test_make_a_portfolio_embed_and_open_it(page, server, chromium):
    sign_in(page, server.base_url, "super", server.password)
    card = create(page, "Discord portfolio")
    url = link(card)
    assert url.startswith(server.s.embed_url + "/embed/")
    # The preview image came from the main server and is a real picture.
    page.wait_for_function("() => document.querySelector('.embed-card img')?.naturalWidth === 1200")
    assert "No websites may show it" in card.inner_text()

    view = chromium.new_context(viewport={"width": 520, "height": 640}).new_page()
    view.goto(url)
    text = view.locator("body").inner_text()
    assert "Discord portfolio" in text and "BTC" in text and "%" in text
    # Amounts and values are off unless switched on.
    assert view.locator(".amount, .value, .total").count() == 0
    assert view.locator("script").count() == 0
    og = view.locator("meta[property='og:image']").get_attribute("content")
    assert og == url + ".png"
    code, png = status(og)
    assert code == 200 and png[:8] == b"\x89PNG\r\n\x1a\n"
    view.screenshot(path="tests/ui/screens/embed_portfolio_page.png")
    view.context.close()
    # The view was counted.
    page.locator("[data-section=embeds]").click()
    page.locator(".embed-card", has_text="1 view").wait_for()


def test_sensitive_items_warn_and_then_show(page, server):
    sign_in(page, server.base_url, "super", server.password)
    card = create(page, "With values", kind="Wallets")
    card.locator("[data-action=edit-embed]").click()
    s = page.locator(".sheet")
    assert "Shows how much you hold" in s.inner_text()
    s.locator("[data-item=values]").check()
    s.locator("[data-item=amounts]").check()
    s.locator("[data-action=save-embed]").click()
    page.locator(".toast", has_text="Embed saved").wait_for()
    card = page.locator(".embed-card", has_text="With values")
    card.locator(".warn-text", has_text="Shows:").wait_for()
    code, body = status(link(card))
    assert code == 200 and b'class="value"' in body and b'class="amount"' in body


class Site:
    """A tiny local website (its own origin) whose page frames an embed."""

    def __init__(self):
        site = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = f"<h1>My blog</h1>{site.snippet}".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.snippet = ""
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://localhost:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


def test_only_listed_websites_may_frame_it(server, chromium, page):
    # Both sites are local: Chromium won't let a public site frame a 127.0.0.1 address at
    # all (real embeds use a public tunnel URL), so "allowed vs not" is tested between ports.
    allowed, other = Site(), Site()
    sign_in(page, server.base_url, "super", server.password)
    card = create(page, "Blog prices", kind="Prices", origins=allowed.origin, theme="terminal")
    url = link(card)
    snippet = card.locator(".copyable input").nth(1).input_value()
    assert snippet.startswith(f'<iframe src="{url}"')
    allowed.snippet = other.snippet = snippet

    ctx = chromium.new_context()
    host = ctx.new_page()
    host.goto(allowed.origin + "/")
    host.frame_locator("iframe").locator("text=Blog prices").wait_for()
    host.screenshot(path="tests/ui/screens/embed_in_allowed_site.png")
    host.goto(other.origin + "/")
    host.wait_for_timeout(1500)
    assert host.frame_locator("iframe").locator("text=Blog prices").count() == 0
    ctx.close()
    allowed.httpd.shutdown()
    other.httpd.shutdown()


def test_turn_off_new_link_and_delete(page, server):
    sign_in(page, server.base_url, "super", server.password)
    card = create(page, "Short lived")
    first = link(card)
    assert status(first)[0] == 200
    card.locator("[data-action=toggle-embed]").click()
    page.locator(".embed-card", has_text="Short lived").locator(".badge", has_text="off").wait_for()
    assert status(first)[0] == 404
    card = page.locator(".embed-card", has_text="Short lived")
    card.locator("[data-action=toggle-embed]").click()
    card.locator(".badge", has_text="on").wait_for()
    card.locator("[data-action=rotate-embed]").click()
    page.wait_for_function(
        "(old) => [...document.querySelectorAll('.embed-card input')].every(i => i.value !== old)",
        arg=first,
    )
    second = link(page.locator(".embed-card", has_text="Short lived"))
    assert status(first)[0] == 404 and status(second)[0] == 200
    page.locator(".embed-card", has_text="Short lived").locator(
        "[data-action=delete-embed]"
    ).click()
    page.locator(".embed-card", has_text="Short lived").wait_for(state="detached")
    assert status(second)[0] == 404


def test_section_needs_the_permission(page, server):
    pw = server.make_user("noembeds_ui", ["wallets.view", "prices.view"])
    sign_in(page, server.base_url, "noembeds_ui", pw)
    open_window(page, "settings")
    assert page.locator(".settings-nav [data-section=embeds]").count() == 0


def test_notice_when_the_embed_server_is_off(page):
    s = SpawnedServer()
    s.start()
    try:
        srv = Server(s)
        srv.api("POST", "/api/setup", {"token": s.setup_token, "password": s.password})
        sign_in(page, s.base_url, "super", s.password)
        m = embeds(page)
        notice = m.locator(".notice.warn", has_text="embed server is off")
        notice.wait_for()
        assert notice.locator("input").input_value() == "crypto-helper embed enable"
    finally:
        page.goto("about:blank")  # nothing may poll the server we're about to stop
        s.stop()
