"""7b: the agent (a real one on a temp socket, systemctl recorded) and the Services API."""

import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.client import AgentError, AgentUnavailable, call
from app.agent.server import AgentServer, Ops
from app.cli.common import CliError
from app.cli.layout import Layout
from app.config import Settings
from app.main import create_app
from tests.conftest import PASSWORD, H
from tests.wallet_helpers import user_with, wallet


class FakeSystem:
    def __init__(self):
        self.calls = []

    def systemctl(self, *args, check=True):
        self.calls.append(args)
        return types.SimpleNamespace(stdout="", returncode=0)

    def unit_properties(self, unit, *props):
        return {"ActiveState": "active", "UnitFileState": "enabled"}


class FakeEmbed:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def start(self, layout, updates, s):
        if self.fail:
            raise CliError(self.fail)
        self.calls.append(("start", updates, s.embed_enabled))

    def stop(self, layout):
        self.calls.append(("stop",))


@pytest.fixture
def agent(tmp_path):
    # Unix socket paths must be short (108 bytes): use a short temp folder.
    folder = tempfile.mkdtemp(prefix="ag-")
    path = os.path.join(folder, "a.sock")
    system, embed = FakeSystem(), FakeEmbed()
    ops = Ops(Layout(root=tmp_path, user="root"), system, lambda: Settings(_env_file=None), embed)
    server = AgentServer(path, {os.getuid()}, ops)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield types.SimpleNamespace(path=path, system=system, embed=embed, server=server)
    server.shutdown()
    server.server_close()


def raw(path, data: bytes) -> dict:
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(5)
        s.connect(path)
        s.sendall(data)
        return json.loads(s.makefile().readline())


# ---- the agent itself ----------------------------------------------------------------------


def test_socket_is_owner_and_group_only(agent):
    assert os.stat(agent.path).st_mode & 0o777 == 0o660


def test_status_and_switches(agent):
    st = call(agent.path, "status", "alice")["services"]
    assert set(st) == {"web", "embed", "backups", "agent", "console", "terminal"}
    assert st["web"]["active"] == "active" and st["terminal"]["active"] == "off"
    assert st["web"]["restarts"] == 0 and st["backups"]["last_result"] == "unknown"
    call(agent.path, "service.set", "alice", service="backups", on=False)
    assert ("disable", "--now", "--quiet", "crypto-helper-backup.timer") in agent.system.calls
    call(agent.path, "service.set", "alice", service="embed", on=True)
    assert agent.embed.calls[-1] == ("start", {"BOT_EMBED_ENABLED": "true"}, True)
    call(agent.path, "service.set", "alice", service="embed", on=False)
    assert agent.embed.calls[-1] == ("stop",)
    call(agent.path, "backup.run", "alice")
    assert ("start", "--no-block", "crypto-helper-backup.service") in agent.system.calls


def test_web_restart_answers_before_restarting(agent):
    assert call(agent.path, "service.restart", "alice", service="web")["restarting"]
    # The answer came back before the restart (which would cut the caller off).
    assert ("restart", "crypto-helper.service") not in agent.system.calls
    for _ in range(30):
        if ("restart", "crypto-helper.service") in agent.system.calls:
            break
        time.sleep(0.05)
    assert ("restart", "crypto-helper.service") in agent.system.calls


@pytest.mark.parametrize(
    "args, message",
    [
        ({"op": "service.set", "service": "web", "on": False}, "can't switch"),
        ({"op": "service.set", "service": "embed"}, "can't switch"),
        ({"op": "service.restart", "service": "backups"}, "can't restart"),
        ({"op": "service.restart", "service": "embed"}, "embed server is off"),
    ],
)
def test_refusals(agent, args, message):
    op = args.pop("op")
    with pytest.raises(AgentError, match=message):
        call(agent.path, op, "alice", **args)
    assert agent.system.calls == []


@pytest.mark.parametrize(
    "data",
    [
        b"not json\n",
        b'{"op": "run", "actor": "a", "command": "rm -rf /"}\n',
        b'{"op": "status", "actor": "a", "extra": 1}\n',
        b'{"op": "status", "actor": "a; reboot"}\n',
        b'{"op": "status", "actor": "a"}',  # no newline: incomplete
    ],
)
def test_anything_else_is_refused(agent, data):
    if not data.endswith(b"\n"):
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(15)
            s.connect(agent.path)
            s.sendall(data)
            s.shutdown(socket.SHUT_WR)
            answer = json.loads(s.makefile().readline())
    else:
        answer = raw(agent.path, data)
    assert answer["ok"] is False
    assert agent.system.calls == []


def test_oversized_request_refused(agent):
    big = json.dumps({"op": "status", "actor": "a" * 40000}).encode() + b"\n"
    assert raw(agent.path, big)["ok"] is False


def test_errors_from_the_job_are_reported(agent):
    agent.embed.fail = "port in use"
    with pytest.raises(AgentError, match="port in use"):
        call(agent.path, "service.set", "alice", service="embed", on=True)


def test_other_users_are_refused(agent):
    agent.server.allowed_uids = {12345}
    with pytest.raises(AgentError, match="not allowed"):
        call(agent.path, "status", "alice")


def test_no_agent():
    with pytest.raises(AgentUnavailable):
        call("/nonexistent/agent.sock", "status", "alice")


# ---- the Services API ----------------------------------------------------------------------


@pytest.fixture
def svc_app(agent, tmp_path):
    a = create_app(
        Settings(
            database_url="sqlite://",
            price_provider="mock",
            agent_socket=agent.path,
            state_dir=str(tmp_path / "state"),
            _env_file=None,
        )
    )
    return a


@pytest.fixture
def admin(svc_app):
    c = TestClient(svc_app)
    c.__enter__()
    c.post("/api/setup", json={"token": svc_app.state.setup_token, "password": PASSWORD}, headers=H)
    c.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
    yield c
    c.__exit__(None, None, None)


def post(c, path, body=None):
    return c.post(path, json=body, headers=H) if body is not None else c.post(path, headers=H)


def test_services_need_the_permission(admin, svc_app):
    assert TestClient(svc_app).get("/api/services").status_code == 401
    viewer = user_with(svc_app, admin, "viewer", ["wallets.view"])
    assert viewer.get("/api/services").status_code == 403
    assert post(viewer, "/api/services/embed/switch", {"on": True}).status_code == 403
    assert (
        viewer.put("/api/services/features", json={"paper_wallets": False}, headers=H).status_code
        == 403
    )
    assert post(viewer, "/api/services/selftest").status_code == 403


def test_services_app_switch_blocks_the_api(admin, svc_app):
    mgr = user_with(svc_app, admin, "svcmgr", ["services.manage"])
    assert mgr.get("/api/services").status_code == 200
    admin.put("/api/apps/services/enabled", json={"enabled": False}, headers=H)
    r = mgr.get("/api/services")
    assert r.status_code == 403 and "turned off for everyone" in r.json()["detail"]
    assert post(mgr, "/api/services/selftest").status_code == 403


def test_overview_with_the_agent(admin):
    data = admin.get("/api/services").json()
    assert data["agent"]["available"] and data["services"]["web"]["active"] == "active"
    assert data["features"] == {
        "paper_wallets": True,
        "practice_transfers": True,
        "practice_prices": False,
        "price_history": True,
    }


def test_switch_and_restart_through_the_agent_are_audited(admin, agent):
    assert post(admin, "/api/services/backups/switch", {"on": False}).status_code == 200
    assert ("disable", "--now", "--quiet", "crypto-helper-backup.timer") in agent.system.calls
    assert post(admin, "/api/services/backups/run").status_code == 200
    assert post(admin, "/api/services/web/switch", {"on": False}).status_code == 404
    agent.embed.fail = "port 8001 is in use"
    r = post(admin, "/api/services/embed/switch", {"on": True})
    assert r.status_code == 502 and "port 8001 is in use" in r.json()["detail"]
    log = admin.get("/api/audit?limit=10").json()
    details = [e["detail"] for e in log if e["action"].startswith("services.")]
    assert "backups off: done" in details and "backup now: done" in details
    assert any(d.startswith("embed on: failed") for d in details)


def test_without_the_agent(admin, agent):
    agent.server.shutdown()
    agent.server.server_close()
    os.unlink(agent.path)
    data = admin.get("/api/services").json()
    assert data["agent"]["available"] is False and data["agent"]["command"].endswith("agent enable")
    r = post(admin, "/api/services/embed/switch", {"on": True})
    assert r.status_code == 503 and "agent enable" in r.json()["detail"]
    # Features work without it.
    r = admin.put("/api/services/features", json={"paper_wallets": False}, headers=H)
    assert r.status_code == 200 and r.json()["paper_wallets"] is False


# ---- feature switches ----------------------------------------------------------------------


def features(c, **kw):
    r = c.put("/api/services/features", json=kw, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_paper_wallets_switch(admin):
    features(admin, paper_wallets=False)
    r = admin.post("/api/wallets", json={"name": "P", "kind": "paper"}, headers=H)
    assert r.status_code == 403 and "Paper wallets are turned off" in r.json()["detail"]
    ex = wallet(admin, "Exchange", kind="exchange")  # other kinds still fine
    r = admin.patch(f"/api/wallets/{ex['id']}", json={"kind": "paper"}, headers=H)
    assert r.status_code == 403
    features(admin, paper_wallets=True)
    wallet(admin, "P")


def test_practice_transfers_switch(admin):
    a, b = wallet(admin, "A"), wallet(admin, "B")
    admin.put(f"/api/wallets/{a['id']}/holdings/BTC", json={"amount": "1"}, headers=H)
    features(admin, practice_transfers=False)
    body = {"from_wallet_id": a["id"], "to_wallet_id": b["id"], "symbol": "BTC", "amount": "0.1"}
    r = admin.post("/api/transfers", json=body, headers=H)
    assert r.status_code == 403 and "Practice transfers are turned off" in r.json()["detail"]
    assert admin.get("/api/transfers").status_code == 200  # history stays visible
    features(admin, practice_transfers=True)
    assert admin.post("/api/transfers", json=body, headers=H).status_code == 201


def test_price_history_switch_is_the_history_setting(admin):
    features(admin, price_history=False)
    assert admin.get("/api/prices/history/settings").json()["settings"]["enabled"] is False
    features(admin, price_history=True)


def test_practice_prices_swap_the_source_and_pause_history(admin, svc_app):
    from app.prices.providers import MockProvider

    class Real:  # stands in for CoinGecko: any provider that isn't the mock
        name = "Real source"
        attribution = "real"

        def fetch(self, ids, fiats):
            return MockProvider().fetch(ids, fiats)

    svc_app.state.prices.real = Real()
    assert admin.get("/api/prices?symbols=BTC").json()["source"] == "Real source"
    features(admin, practice_prices=True)
    assert admin.get("/api/prices?symbols=BTC").json()["source"].startswith("Mock")
    assert svc_app.state.history_job.tick() == {"skipped": "practice prices are on"}
    features(admin, practice_prices=False)
    assert admin.get("/api/prices?symbols=BTC").json()["source"] == "Real source"


def test_feature_changes_are_validated_and_audited(admin):
    assert admin.put("/api/services/features", json={}, headers=H).status_code == 422
    assert admin.put("/api/services/features", json={"nope": True}, headers=H).status_code == 422
    features(admin, paper_wallets=False)
    entry = admin.get("/api/audit?limit=1").json()[0]
    assert entry["action"] == "services.feature" and entry["detail"] == "paper_wallets off"


# ---- self-test -----------------------------------------------------------------------------

FAKE_TESTER = (
    "import sys, json, time; time.sleep(0.3); "
    "p = sys.argv[sys.argv.index('--report') + 1]; "
    "json.dump({'target': 'spawn', 'passed': 2, 'failed': 1, 'results': ["
    "{'suite': 'a', 'check': 'x', 'ok': True, 'message': ''},"
    "{'suite': 'a', 'check': 'y', 'ok': True, 'message': ''},"
    "{'suite': 'b', 'check': 'z', 'ok': False, 'message': 'boom'}]}, open(p, 'w')); "
    "print('1 failed'); sys.exit(1)"
)


def test_selftest_runs_in_the_background_one_at_a_time(admin, svc_app, tmp_path):
    from app.selftest import SelfTest

    svc_app.state.selftest = SelfTest(tmp_path, command=[sys.executable, "-c", FAKE_TESTER])
    r = post(admin, "/api/services/selftest")
    assert r.status_code == 202 and r.json()["running"]
    assert post(admin, "/api/services/selftest").status_code == 409
    for _ in range(100):
        st = admin.get("/api/services/selftest").json()
        if not st["running"]:
            break
        time.sleep(0.05)
    last = st["last"]
    assert last["ok"] is False and last["passed"] == 2 and last["failed"] == 1
    assert last["failures"] == [{"suite": "b", "check": "z", "message": "boom"}]
    assert last["started_by"] == "super" and "1 failed" in last["log"]
    assert json.loads(Path(tmp_path, "selftest.json").read_text())["failed"] == 1


def test_throwaway_servers_never_reach_the_real_agent(monkeypatch):
    from app.config import Settings as S
    from toolchain.tester.server import SpawnedServer

    monkeypatch.setenv("BOT_AGENT_SOCKET", S().agent_socket)
    monkeypatch.setenv("BOT_COOKIE_SECURE", "true")  # a live install's setting
    monkeypatch.setenv("BOT_EMBED_PUBLIC_URL", "https://real.example.com")
    s = SpawnedServer()
    captured = {}
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: captured.update(env=k["env"]) or (_ for _ in ()).throw(StopIteration),
    )
    with pytest.raises(StopIteration):
        s.start()
    assert captured["env"]["BOT_AGENT_SOCKET"].startswith(s.tmp.name)
    assert captured["env"]["BOT_AGENT_SOCKET"] != S().agent_socket
    assert "BOT_COOKIE_SECURE" not in captured["env"]
    assert "BOT_EMBED_PUBLIC_URL" not in captured["env"]
    s.tmp.cleanup()


def test_update_check_runs_the_fixed_command(tmp_path):
    from app.agent.protocol import Request as AgentRequest

    ran = []

    def run(args, timeout):
        ran.append(args)
        return 0, "==> Checking for updates on dev\nabc1234 Newer things\n\nRun `sudo ...`\n"

    ops = Ops(Layout(root=tmp_path, user="root"), FakeSystem(),
              lambda: Settings(_env_file=None), FakeEmbed(), run=run)  # fmt: skip
    out = ops.handle(AgentRequest(op="update.check", actor="<health>"))
    assert out == {"available": True, "commits": 1, "newest": "abc1234 Newer things"}
    assert ran[0][1:] == ["update", "--check"]  # never `update` without --check
