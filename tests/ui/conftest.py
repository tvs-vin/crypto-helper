"""Real-browser tests: a real server process and headless Chromium (Playwright).

Skipped automatically when Playwright or its Chromium isn't installed. Screenshots of each
scenario land in tests/ui/screens/ (gitignored) for a human to look at.
"""

import json
import urllib.request
from pathlib import Path

import pytest

from toolchain.tester.server import SpawnedServer

SCREENS = Path(__file__).with_name("screens")

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/ui/" in str(item.fspath):
            item.add_marker(pytest.mark.ui)


@pytest.fixture(scope="session")
def chromium():
    if sync_playwright is None:
        pytest.skip("playwright isn't installed")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # pragma: no cover
            pytest.skip(f"Chromium isn't available: {e}")
        yield browser
        browser.close()


def _api(server, method, path, body=None, cookie=None):
    req = urllib.request.Request(
        server.base_url + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Requested-With": "fetch",
            **({"Cookie": cookie} if cookie else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.headers, json.loads(r.read() or b"null")


class Server:
    """A spawned server with `super` created; helpers to drive its API directly."""

    def __init__(self, spawned: SpawnedServer):
        self.s = spawned
        self.base_url = spawned.base_url
        self.password = spawned.password

    def api(self, method, path, body=None, cookie=None):
        return _api(self.s, method, path, body, cookie)

    def admin_cookie(self) -> str:
        _, headers, _ = self.api(
            "POST", "/api/auth/login", {"username": "super", "password": self.password}
        )
        return headers["set-cookie"].split(";")[0]

    def make_user(self, name, perms, password="ui-test-passphrase"):
        self.api(
            "POST",
            "/api/users",
            {"username": name, "password": password, "permissions": perms},
            self.admin_cookie(),
        )
        return password


@pytest.fixture(scope="module")
def server():
    s = SpawnedServer()
    s.start()
    _api(s, "POST", "/api/setup", {"token": s.setup_token, "password": s.password})
    yield Server(s)
    s.stop()


@pytest.fixture
def fresh_server():
    s = SpawnedServer()
    s.start()
    yield s
    s.stop()


@pytest.fixture
def page(chromium, request):
    context = chromium.new_context(viewport={"width": 1440, "height": 900})
    pg = context.new_page()
    problems = []
    pg.on(
        "console",
        lambda m: (
            problems.append(f"{m.type}: {m.text}")
            if m.type == "error" and "401" not in m.text
            else None
        ),
    )
    pg.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    pg.problems = problems
    yield pg
    SCREENS.mkdir(exist_ok=True)
    pg.screenshot(path=str(SCREENS / f"{request.node.name}.png"))
    context.close()
    # Any JavaScript error or Content-Security-Policy violation fails the test.
    assert not problems, problems


def sign_in(pg, base_url, username, password):
    pg.goto(base_url + "/")
    pg.wait_for_selector("#login-username")
    pg.fill("#login-username", username)
    pg.fill("#login-password", password)
    pg.click("button[type=submit]")
    pg.wait_for_selector("body[data-session=ready]")


def open_window(pg, panel):
    pg.click("[data-action=launcher]")
    pg.click(f".menu-item[data-panel={panel}]")
    pg.wait_for_selector(f".window[data-panel={panel}]")


def box(pg, panel):
    return pg.locator(f".window[data-panel={panel}]").bounding_box()


def wait_saved(pg):
    """Layout saves are debounced (600 ms); wait for the PATCH to finish."""
    with pg.expect_response(
        lambda r: r.url.endswith("/api/me/preferences") and r.request.method == "PATCH"
    ):
        pass
