"""7c in a real browser: switching Console and Terminal on in Services, running a console
command, and a terminal session typed into through xterm.js. A test agent stands in for the
real one: console commands are faked and the "login" is a plain shell."""

import os
import tempfile
import threading
import time
from pathlib import Path

import pyotp
import pytest

from app.agent.server import AgentServer, Ops
from app.cli.layout import Layout
from app.config import Settings
from tests.test_agent import FakeEmbed, FakeSystem
from tests.test_shell import SHELL, start_bridge
from tests.ui.conftest import Server, _api, close_walkthrough, open_window
from toolchain.tester.server import SpawnedServer


@pytest.fixture(scope="module")
def agent():
    root = Path(tempfile.mkdtemp())
    layout = Layout(root=root, user="root")
    layout.etc.mkdir(parents=True)
    layout.config.write_text("BOT_HOST=127.0.0.1\n")
    path = os.path.join(tempfile.mkdtemp(prefix="ag-"), "a.sock")

    def settings():
        return Settings(_env_file=str(layout.config), agent_socket=path)

    def run(args, timeout):
        return 0, f"Ran: crypto-helper {' '.join(args[1:])}\nAll good.\n"

    def start(lay, session, sock, cols, rows, host):
        start_bridge(sock, cols, rows, command=SHELL)

    ops = Ops(layout, FakeSystem(), settings, FakeEmbed(), run=run, start_terminal=start)
    server = AgentServer(path, {os.getuid()}, ops)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.path = path
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def server(agent):
    s = SpawnedServer(extra_env={"BOT_AGENT_SOCKET": agent.path})
    s.start()
    srv = Server(s)
    srv.api("POST", "/api/setup", {"token": s.setup_token, "password": s.password})
    # super turns on 2FA (both windows need it).
    cookie = srv.admin_cookie()
    _, _, setup = _api(s, "POST", "/api/auth/totp/setup", None, cookie)
    srv.secret = setup["secret"]
    _, _, enabled = _api(
        s,
        "POST",
        "/api/auth/totp/enable",
        {"code": pyotp.TOTP(srv.secret).now(), "password": s.password},
        cookie,
    )
    # Sign-ins use recovery codes, so the authenticator codes (one per 30 s, each usable
    # once) are left for opening terminals.
    srv.recovery = list(enabled["recovery_codes"])
    yield srv
    s.stop()


def sign_in_2fa(page, srv):
    page.goto(srv.base_url + "/")
    page.wait_for_selector("#login-username")
    page.fill("#login-username", "super")
    page.fill("#login-password", srv.password)
    page.click("button[type=submit]")
    page.get_by_role("button", name="Use a recovery code").click()
    page.fill("#login-code", srv.recovery.pop())
    page.get_by_role("button", name="Verify").click()
    page.wait_for_selector("body[data-session=ready]")
    close_walkthrough(page)


def switch_on(page, key):
    open_window(page, "services")
    w = page.locator(".window[data-panel=services]")
    w.locator(f"[data-action=switch-{key}][aria-checked=false]").click()
    page.locator(".toast", has_text=f"{key.capitalize()} on").wait_for()


def test_console_runs_a_command(page, server):
    sign_in_2fa(page, server)
    switch_on(page, "console")
    open_window(page, "console")
    w = page.locator(".window[data-panel=console]")
    w.locator("[data-command=doctor]").click()
    w.locator(".console-log", has_text="Ran: crypto-helper doctor").wait_for()
    assert w.locator(".badge.ok").inner_text() == "ok"
    page.screenshot(path="tests/ui/screens/console.png")


def test_terminal_session_through_xterm(page, server):
    marker = Path(tempfile.mkdtemp()) / "typed-in-the-terminal"
    sign_in_2fa(page, server)
    switch_on(page, "terminal")
    open_window(page, "terminal")
    w = page.locator(".window[data-panel=terminal]")
    w.locator("[name=password]").fill(server.password)
    w.locator("[name=code]").fill(pyotp.TOTP(server.secret).at(time.time() + 30))
    w.locator("[data-action=open-terminal]").click()
    w.locator(".terminal-screen canvas").first.wait_for()
    assert page.locator("style").count() == 0  # nothing the CSP would block
    page.wait_for_timeout(500)
    page.keyboard.type(f"echo hello-from-the-browser; touch {marker}\n")
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.exists()
    page.screenshot(path="tests/ui/screens/terminal.png")
    page.keyboard.type("exit\n")
    w.locator(".terminal-ended", has_text="The session ended").wait_for()


def test_terminal_asks_again_and_refuses_a_bad_code(page, server):
    sign_in_2fa(page, server)
    open_window(page, "terminal")
    w = page.locator(".window[data-panel=terminal]")
    w.locator("[name=password]").fill(server.password)
    w.locator("[name=code]").fill("000000")
    w.locator("[data-action=open-terminal]").click()
    w.locator(".notice.error", has_text="code").wait_for()
    assert w.locator(".terminal-screen").count() == 0
