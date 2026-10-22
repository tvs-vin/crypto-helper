"""12a: changing where the web UI listens and who may connect, from the browser. The rules,
the agent writing it (and putting it back unless confirmed), and the API's lock-out guards.
Every config file here is a stand-in under tmp_path (tests run as root)."""

import os
import tempfile
import threading
import time
import types

import pytest
from fastapi.testclient import TestClient

from app import netconfig
from app.agent.client import AgentError, call
from app.agent.server import AgentServer, Ops
from app.cli.layout import Layout
from app.config import Settings
from app.main import create_app
from tests.conftest import PASSWORD, H
from tests.test_agent import FakeEmbed, FakeSystem

CONFIG = """# Crypto Helper
BOT_HOST=127.0.0.1
BOT_ALLOWED_NETWORKS=127.0.0.0/8,::1/128
BOT_SECRET_KEY_FILE=/etc/crypto-helper/secret.key
"""

# ---- the rules -------------------------------------------------------------------------------


def test_good_settings_are_normalised():
    hosts, nets = netconfig.check(
        ["127.0.0.1", " 100.64.39.116", "127.0.0.1"], ["127.0.0.0/8", "100.64.1.9/16"]
    )
    assert hosts == ["127.0.0.1", "100.64.39.116"]
    assert nets == ["127.0.0.0/8", "100.64.0.0/16"]
    assert netconfig.config_updates(hosts, nets) == {
        "BOT_HOST": "127.0.0.1,100.64.39.116",
        "BOT_ALLOWED_NETWORKS": "127.0.0.0/8,100.64.0.0/16",
        "BOT_ALLOW_REMOTE_BIND": "true",
    }
    assert netconfig.config_updates(["127.0.0.1"], ["127.0.0.0/8"])["BOT_ALLOW_REMOTE_BIND"] == (
        "false"
    )


@pytest.mark.parametrize(
    ("hosts", "nets", "message"),
    [
        (["127.0.0.1", "0.0.0.0"], ["127.0.0.0/8"], "every network interface"),
        (["127.0.0.1", "::"], ["127.0.0.0/8"], "every network interface"),
        (["100.64.39.116"], ["127.0.0.0/8"], "Keep 127.0.0.1"),
        (["127.0.0.1"], ["100.64.0.0/10"], "Keep 127.0.0.0/8"),
        (["127.0.0.1"], ["127.0.0.0/8", "0.0.0.0/0"], "everyone connect"),
        (["127.0.0.1"], ["127.0.0.0/8", "::/0"], "everyone connect"),
        (["localhost"], ["127.0.0.0/8"], "isn't an IP address"),
        (["127.0.0.1"], ["127.0.0.0/8", "home"], "isn't an address or network"),
        (["127.0.0.1", "fe80::1"], ["127.0.0.0/8"], "can't be listened on"),
        ([], ["127.0.0.0/8"], "Between 1"),
        (["127.0.0.1"] + [f"10.0.0.{i}" for i in range(8)], ["127.0.0.0/8"], "Between 1"),
    ],
)
def test_refused(hosts, nets, message):
    with pytest.raises(netconfig.NetConfigError, match=message):
        netconfig.check(hosts, nets)


def test_this_machines_addresses():
    found = netconfig.local_addresses()
    assert {"address": "127.0.0.1", "interface": "lo", "kind": "this machine only"} in found
    assert netconfig.is_local("127.0.0.1")
    assert not netconfig.is_local("192.0.2.1")  # TEST-NET-1: never this machine's
    assert netconfig.kind_of("100.64.39.116", "wt0") == "NetBird"
    assert netconfig.kind_of("100.100.1.2", "tailscale0") == "Tailscale"
    assert netconfig.kind_of("100.70.0.1", "eth9") == "VPN (100.64.0.0/10)"
    assert netconfig.kind_of("192.168.1.5", "eth0") == "local network"
    assert netconfig.kind_of("8.8.8.8", "eth0") == "public internet"


def test_ipv6_list_skips_link_local(tmp_path):
    f = tmp_path / "if_inet6"
    f.write_text(
        "00000000000000000000000000000001 01 80 10 80       lo\n"
        "fe800000000000000000000000000001 02 40 20 80     eth0\n"
        "fdd412808ccbff8bbe2411fffeabf856 02 40 00 00     eth0\n"
    )
    assert netconfig._ipv6_interfaces(str(f)) == [
        ("lo", "::1"),
        ("eth0", "fdd4:1280:8ccb:ff8b:be24:11ff:feab:f856"),
    ]


# ---- the agent -------------------------------------------------------------------------------


@pytest.fixture
def agent(tmp_path):
    layout = Layout(root=tmp_path, user="root")
    layout.etc.mkdir(parents=True)
    layout.config.write_text(CONFIG)
    folder = tempfile.mkdtemp(prefix="ag-")
    path = os.path.join(folder, "a.sock")
    system = FakeSystem()

    def settings():
        return Settings(_env_file=str(layout.config))

    ops = Ops(layout, system, settings, FakeEmbed())
    ops.revert_seconds = 1
    ops.min_confirm_seconds = 0.2
    server = AgentServer(path, {os.getuid()}, ops)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield types.SimpleNamespace(path=path, system=system, ops=ops, layout=layout)
    server.shutdown()
    server.server_close()


def restarts(system):
    time.sleep(0.8)  # restarts happen just after the answer
    return [c for c in system.calls if c[0] == "restart"]


def test_confirm_too_early_is_refused(agent):
    agent.ops.min_confirm_seconds = 5
    call(agent.path, "network.set", "super", hosts=["127.0.0.1"], allowed_networks=["127.0.0.0/8"])
    with pytest.raises(AgentError, match="too early"):
        call(agent.path, "network.confirm", "super")  # the old web UI, before its restart


def test_set_then_confirm_keeps_it(agent):
    out = call(
        agent.path,
        "network.set",
        "super",
        hosts=["127.0.0.1", "100.64.39.116"],
        allowed_networks=["127.0.0.0/8", "100.64.0.0/16"],
    )
    assert out["confirm_within"] == 1
    text = agent.layout.config.read_text()
    assert "BOT_HOST=127.0.0.1,100.64.39.116\n" in text
    assert "BOT_ALLOWED_NETWORKS=127.0.0.0/8,100.64.0.0/16\n" in text
    assert "BOT_ALLOW_REMOTE_BIND=true" in text
    assert "BOT_SECRET_KEY_FILE=/etc/crypto-helper/secret.key" in text  # the rest kept
    assert restarts(agent.system) == [("restart", "crypto-helper.service")]
    assert call(agent.path, "network.state", "super")["pending"] is True
    assert call(agent.path, "network.confirm", "super") == {"ok": True, "confirmed": True}
    time.sleep(1.3)  # past the deadline: nothing is put back
    assert "BOT_HOST=127.0.0.1,100.64.39.116" in agent.layout.config.read_text()
    assert not agent.ops.revert_file.exists()
    with pytest.raises(AgentError, match="no network change to confirm"):
        call(agent.path, "network.confirm", "super")


def test_a_confirmed_changes_timer_cant_undo_the_next_change(agent):
    call(agent.path, "network.set", "super", hosts=["127.0.0.1"], allowed_networks=["127.0.0.0/8"])
    time.sleep(0.3)
    call(agent.path, "network.confirm", "super")
    agent.ops.revert_seconds = 10  # the second change has its own, longer, deadline
    call(
        agent.path,
        "network.set",
        "super",
        hosts=["127.0.0.1", "100.64.39.116"],
        allowed_networks=["127.0.0.0/8"],
    )
    time.sleep(1.3)  # past the first change's deadline
    assert "BOT_HOST=127.0.0.1,100.64.39.116" in agent.layout.config.read_text()
    assert agent.ops.revert_file.exists()  # still waiting for its own confirmation


def test_unconfirmed_change_is_put_back(agent):
    call(
        agent.path,
        "network.set",
        "super",
        hosts=["127.0.0.1", "100.64.39.116"],
        allowed_networks=["127.0.0.0/8"],
    )
    with pytest.raises(AgentError, match="still waiting to be confirmed"):
        call(
            agent.path,
            "network.set",
            "super",
            hosts=["127.0.0.1"],
            allowed_networks=["127.0.0.0/8"],
        )
    time.sleep(1.8)
    assert agent.layout.config.read_text() == CONFIG  # exactly as before
    assert not agent.ops.revert_file.exists()
    assert len(restarts(agent.system)) == 2  # the change, then putting it back


def test_agent_start_undoes_a_change_it_cant_vouch_for(agent):
    agent.ops.revert_file.write_text(CONFIG)
    agent.layout.config.write_text(CONFIG.replace("127.0.0.1\n", "127.0.0.1,10.9.9.9\n"))
    assert agent.ops.revert() is True
    assert agent.layout.config.read_text() == CONFIG
    assert agent.ops.revert() is False  # nothing left to undo


def test_agent_checks_the_rules_itself(agent):
    with pytest.raises(AgentError, match="every network interface"):
        call(
            agent.path, "network.set", "super", hosts=["0.0.0.0"], allowed_networks=["127.0.0.0/8"]
        )
    assert agent.layout.config.read_text() == CONFIG
    assert not agent.ops.revert_file.exists()


# ---- the API ---------------------------------------------------------------------------------


@pytest.fixture
def web(agent, tmp_path):
    app = create_app(
        Settings(
            database_url="sqlite://",
            price_provider="mock",
            agent_socket=agent.path,
            state_dir=str(tmp_path / "state"),
            _env_file=None,
        )
    )
    # The browser reached 127.0.0.1 from 127.0.0.1 (like an SSH tunnel).
    c = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    c.__enter__()
    c.post("/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H)
    c.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
    yield app, c
    c.__exit__(None, None, None)


def test_read_the_setup(web):
    _, c = web
    got = c.get("/api/server/network").json()
    assert got["hosts"] == ["127.0.0.1"] and got["agent"] is True and got["pending"] is False
    assert got["you"] == {"client_ip": "127.0.0.1", "via": "127.0.0.1"}
    lo = next(a for a in got["addresses"] if a["address"] == "127.0.0.1")
    assert lo["listening"] is True


def test_change_and_confirm_through_the_api(web, agent):
    _, c = web
    lan = next(
        (
            a["address"]
            for a in netconfig.local_addresses()
            if not a["address"].startswith(("127.", "::1"))
        ),
        None,
    )
    hosts = ["127.0.0.1"] + ([lan] if lan else [])
    r = c.put(
        "/api/server/network",
        json={"hosts": hosts, "allowed_networks": ["127.0.0.0/8", "100.64.0.0/10"]},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert f"BOT_HOST={','.join(hosts)}" in agent.layout.config.read_text()
    time.sleep(0.3)  # the agent only takes a confirmation once the web UI could have restarted
    assert c.post("/api/server/network/confirm", headers=H).status_code == 200
    actions = [e["action"] for e in c.get("/api/audit?q=server.network").json()]
    assert actions == ["server.network.confirm", "server.network"]


@pytest.mark.parametrize(
    ("hosts", "nets", "message"),
    [
        (["127.0.0.1", "192.0.2.1"], ["127.0.0.0/8"], "isn't an address of this machine"),
        (["127.0.0.1", "0.0.0.0"], ["127.0.0.0/8"], "every network interface"),
    ],
)
def test_api_refusals(web, agent, hosts, nets, message):
    _, c = web
    r = c.put("/api/server/network", json={"hosts": hosts, "allowed_networks": nets}, headers=H)
    assert r.status_code == 422 and message in r.json()["detail"]
    assert agent.layout.config.read_text() == CONFIG


def test_cant_cut_yourself_off(web, agent, monkeypatch):
    app, _ = web
    # As if this machine had the NetBird address (it doesn't on CI).
    monkeypatch.setattr(netconfig, "is_local", lambda ip: ip in ("127.0.0.1", "100.64.39.116"))
    # Reached over NetBird: dropping that address, or that network, is refused.
    c = TestClient(app, base_url="http://100.64.39.116:8000", client=("100.64.5.6", 40000))
    c.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
    r = c.put(
        "/api/server/network",
        json={"hosts": ["127.0.0.1"], "allowed_networks": ["127.0.0.0/8", "100.64.0.0/10"]},
        headers=H,
    )
    assert r.status_code == 422 and "Keep 100.64.39.116" in r.json()["detail"]
    lan_only = {"hosts": ["127.0.0.1", "100.64.39.116"], "allowed_networks": ["127.0.0.0/8"]}
    r = c.put("/api/server/network", json=lan_only, headers=H)
    assert r.status_code == 422 and "100.64.5.6" in r.json()["detail"]
    assert agent.layout.config.read_text() == CONFIG


def test_only_super(web):
    app, c = web
    body = {
        "username": "admin2",
        "password": "another-long-passphrase",
        "permissions": ["services.manage", "users.manage"],
    }
    c.post("/api/users", json=body, headers=H)
    a = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50001))
    a.post(
        "/api/auth/login",
        json={"username": "admin2", "password": "another-long-passphrase"},
        headers=H,
    )
    assert a.get("/api/server/network").status_code == 403
    r = a.put(
        "/api/server/network",
        json={"hosts": ["127.0.0.1"], "allowed_networks": ["127.0.0.0/8"]},
        headers=H,
    )
    assert r.status_code == 403


def test_without_the_agent(tmp_path):
    app = create_app(
        Settings(
            database_url="sqlite://",
            price_provider="mock",
            agent_socket=str(tmp_path / "none.sock"),
            state_dir=str(tmp_path / "state"),
            _env_file=None,
        )
    )
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1)) as c:
        c.post("/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H)
        c.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
        got = c.get("/api/server/network").json()
        assert (
            got["agent"] is False and got["manual"]["then"] == "sudo crypto-helper service restart"
        )
        r = c.put(
            "/api/server/network",
            json={"hosts": ["127.0.0.1"], "allowed_networks": ["127.0.0.0/8"]},
            headers=H,
        )
        assert r.status_code == 503 and "crypto-helper agent enable" in r.json()["detail"]
