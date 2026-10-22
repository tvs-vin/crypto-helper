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
    # The pretend exchange (no network), and no background sync: tests sync on purpose.
    s = SpawnedServer(extra_env={"BOT_SYNC_DEMO": "true", "BOT_SYNC_BACKGROUND": "false"})
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
    # Chromium logs every 4xx response as "Failed to load resource"; the app expects and
    # handles those (sign-in checks, refused input). Real script errors still fail the test.
    pg.on(
        "console",
        lambda m: (
            problems.append(f"{m.type}: {m.text}")
            if m.type == "error" and "the server responded with a status of 4" not in m.text
            else None
        ),
    )
    pg.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    # A refused layout save only shows a toast, so it slipped through once (the App manager
    # and Services windows weren't allowed in saved layouts): fail on it, and on any 5xx.
    pg.on(
        "response",
        lambda r: (
            problems.append(f"{r.status} from {r.request.method} {r.url}")
            # 401 is fine: an expired session brings the sign-in box back by design.
            if r.status >= 500 or ("/api/me/preferences" in r.url and r.status == 422)
            else None
        ),
    )
    pg.problems = problems
    yield pg
    SCREENS.mkdir(exist_ok=True)
    pg.screenshot(path=str(SCREENS / f"{request.node.name}.png"))
    context.close()
    if problems:
        # Show the server's side of it: tracebacks are in its log.
        for name in ("server", "fresh_server"):
            if name in request.fixturenames:
                try:
                    srv = request.getfixturevalue(name)
                except AssertionError:  # already torn down (function-scoped): no log to show
                    continue
                log = "".join((getattr(srv, "s", srv)).output[-80:])
                print(f"\n----- {name} log (last lines) -----\n{log}")
    # Any JavaScript error or Content-Security-Policy violation fails the test.
    assert not problems, problems


def sign_in(pg, base_url, username, password):
    pg.goto(base_url + "/")
    pg.wait_for_selector("#login-username")
    pg.fill("#login-username", username)
    pg.fill("#login-password", password)
    pg.click("button[type=submit]")
    pg.wait_for_selector("body[data-session=ready]")
    close_walkthrough(pg)


def close_walkthrough(pg):
    """An account's first sign-in opens the walkthrough over the desktop: put it away the way
    a person would (hide it, then close its bar), so it doesn't open again."""
    if pg.evaluate("() => document.body.dataset.walkthrough === 'open'"):
        pg.click("[data-action=wizard-hide]")
        with pg.expect_response(lambda r: r.url.endswith("/api/onboarding/finish")):
            pg.click("[data-action=wizard-close]")


def open_window(pg, panel):
    pg.click("[data-action=launcher]")
    pg.click(f".menu-item[data-panel={panel}]")
    pg.wait_for_selector(f".window[data-panel={panel}]")


def until(pg, check, timeout=10_000, what="the page to settle"):
    """Wait until check() is true (animations, debounced saves): never a fixed sleep, which
    passes on an idle machine and fails when the checks run on every core."""
    for _ in range(timeout // 100):
        if check():
            return
        pg.wait_for_timeout(100)
    assert check(), f"timed out waiting for {what}"


def box(pg, panel):
    return pg.locator(f".window[data-panel={panel}]").bounding_box()


def wait_saved(pg):
    """Layout saves are debounced (600 ms); wait for the PATCH to finish."""
    with pg.expect_response(
        lambda r: r.url.endswith("/api/me/preferences") and r.request.method == "PATCH"
    ):
        pass
