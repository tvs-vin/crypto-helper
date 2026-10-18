"""7b in a real browser: the Services window, with a test agent (systemctl recorded, nothing
real is touched) and without one."""

import os
import tempfile
import threading

import pytest

from app.agent.server import AgentServer, Ops
from app.cli.layout import Layout
from app.config import Settings
from tests.test_agent import FakeEmbed, FakeSystem
from tests.ui.conftest import Server, open_window, sign_in
from toolchain.tester.server import SpawnedServer


@pytest.fixture(scope="module")
def agent():
    path = os.path.join(tempfile.mkdtemp(prefix="ag-"), "a.sock")
    system, embed = FakeSystem(), FakeEmbed()
    ops = Ops(
        Layout(root=tempfile.mkdtemp(), user="root"),
        system,
        lambda: Settings(_env_file=None),
        embed,
    )
    server = AgentServer(path, {os.getuid()}, ops)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.fake = (system, embed)
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
    yield srv
    s.stop()


def services(pg):
    open_window(pg, "services")
    pg.locator(".service-row[data-service=web]").wait_for()
    return pg.locator(".window[data-panel=services]")


def test_system_services_through_the_agent(page, server, agent):
    system, embed = agent.fake
    sign_in(page, server.base_url, "super", server.password)
    w = services(page)
    assert w.locator(".notice.warn").count() == 0
    w.locator("[data-action=switch-embed]").click()
    page.locator(".toast", has_text="Embed server on").wait_for()
    assert embed.calls[-1][0] == "start"
    w.locator("[data-action=backup-now]").click()
    page.locator(".toast", has_text="Backup started").wait_for()
    assert ("start", "--no-block", "crypto-helper-backup.service") in system.calls
    w.locator("[data-action=restart-web]").click()
    page.locator(".toast", has_text="Restarting the web UI").wait_for()
    page.screenshot(path="tests/ui/screens/services.png")


def test_feature_switches_take_effect(page, server):
    sign_in(page, server.base_url, "super", server.password)
    w = services(page)
    w.locator("[data-action=feature-paper_wallets]").click()
    page.locator(".toast", has_text="Paper wallets off").wait_for()
    status, body = page.evaluate(
        """async () => { const r = await fetch('/api/wallets', {method: 'POST',
             headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'},
             body: JSON.stringify({name: 'P', kind: 'paper'})});
           return [r.status, await r.json()]; }"""
    )
    assert status == 403 and "Paper wallets are turned off" in body["detail"]
    w.locator("[data-action=feature-paper_wallets][aria-checked=false]").click()
    page.locator(".toast", has_text="Paper wallets on").wait_for()
    # Practice prices: on shows the warning, and prices say where they come from.
    w.locator("[data-action=feature-practice_prices]").click()
    w.locator(".warn-text", has_text="every price in the app").wait_for()
    w.locator("[data-action=feature-practice_prices][aria-checked=true]").click()
    w.locator("[data-action=feature-practice_prices][aria-checked=false]").wait_for()


def test_without_the_agent(page, agent):
    s = SpawnedServer(extra_env={"BOT_AGENT_SOCKET": "/nonexistent/agent.sock"})
    s.start()
    try:
        Server(s).api("POST", "/api/setup", {"token": s.setup_token, "password": s.password})
        sign_in(page, s.base_url, "super", s.password)
        w = services(page)
        notice = w.locator(".notice.warn", has_text="The agent is off")
        notice.wait_for()
        assert notice.locator("input").input_value() == "sudo crypto-helper agent enable"
        assert w.locator("[data-action=switch-embed]").is_disabled()
        assert w.locator("[data-action=backup-now]").is_disabled()
        assert not w.locator("[data-action=feature-paper_wallets]").is_disabled()
        page.screenshot(path="tests/ui/screens/services_without_agent.png")
    finally:
        page.goto("about:blank")  # nothing may poll the server we're about to stop
        s.stop()


def test_hidden_without_the_permission(page, server):
    pw = server.make_user("noservices_ui", ["wallets.view"])
    sign_in(page, server.base_url, "noservices_ui", pw)
    page.click("[data-action=launcher]")
    assert page.locator(".menu-item[data-panel=services]").count() == 0
