import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.netaccess import client_allowed, host_covered, parse_hosts, parse_networks

NETBIRD = "127.0.0.0/8,100.64.0.0/16"


def test_parse_hosts():
    assert parse_hosts("127.0.0.1, 100.64.39.116,127.0.0.1") == ["127.0.0.1", "100.64.39.116"]
    assert parse_hosts("") == ["127.0.0.1"]


def test_parse_networks():
    nets = parse_networks(NETBIRD)
    assert [str(n) for n in nets] == ["127.0.0.0/8", "100.64.0.0/16"]
    assert parse_networks("*") is None
    assert [str(n) for n in parse_networks("100.64.1.5")] == ["100.64.1.5/32"]
    with pytest.raises(ValueError, match="isn't an address"):
        parse_networks("netbird")


@pytest.mark.parametrize(
    ("ip", "ok"),
    [
        ("127.0.0.1", True),
        ("100.64.39.116", True),
        ("100.64.255.1", True),
        ("100.65.0.1", False),  # outside the NetBird /16
        ("192.168.50.20", False),  # home network
        ("8.8.8.8", False),
        ("::ffff:100.64.1.2", True),
        ("testclient", False),
        (None, False),
    ],
)
def test_client_allowed(ip, ok):
    assert client_allowed(ip, parse_networks(NETBIRD)) is ok


def test_host_covered():
    nets = parse_networks("127.0.0.0/8")
    assert host_covered("127.0.0.1", nets) and not host_covered("100.64.39.116", nets)


@pytest.mark.parametrize(
    ("client", "status"),
    [
        (("127.0.0.1", 5000), 200),
        (("100.64.12.34", 5000), 200),
        (("192.168.50.20", 5000), 403),
        (("203.0.113.9", 5000), 403),
    ],
)
def test_app_refuses_clients_outside_the_allowlist(monkeypatch, client, status):
    monkeypatch.setenv("BOT_ALLOWED_NETWORKS", NETBIRD)
    app = create_app(Settings(database_url="sqlite://", _env_file=None))
    with TestClient(app, client=client) as c:
        r = c.get("/api/setup/status")
    assert r.status_code == status
    assert r.headers["x-frame-options"] == "DENY"  # even the refusal has security headers
    if status == 403:
        assert r.text == "Forbidden"  # nothing about the app leaks


# ---- a real server on two addresses ------------------------------------------------------


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get_from(source_ip: str, url_host: str, port: int) -> int:
    """GET the setup status from a chosen source address (127.x are all on loopback)."""
    conn = socket.create_connection((url_host, port), timeout=5, source_address=(source_ip, 0))
    conn.sendall(
        f"GET /api/setup/status HTTP/1.1\r\nHost: {url_host}\r\nConnection: close\r\n\r\n".encode()
    )
    data = b""
    while chunk := conn.recv(4096):
        data += chunk
    conn.close()
    return int(data.split()[1])


def test_real_server_listens_on_two_addresses_and_checks_sources(tmp_path):
    port = _free_port()
    env = {
        **os.environ,
        "BOT_HOST": "127.0.0.1,127.0.0.2",
        "BOT_PORT": str(port),
        "BOT_ALLOWED_NETWORKS": "127.0.0.1/32,127.0.0.2/32",
        "BOT_ALLOW_REMOTE_BIND": "false",
        "BOT_DATABASE_URL": f"sqlite:///{tmp_path}/n.db",
        "BOT_STATE_DIR": str(tmp_path),
        "CRYPTO_HELPER_CONFIG": str(tmp_path / "empty.env"),
    }
    (tmp_path / "empty.env").touch()
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.cli", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/setup/status", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        assert _get_from("127.0.0.1", "127.0.0.1", port) == 200
        assert _get_from("127.0.0.2", "127.0.0.2", port) == 200  # second address works
        assert _get_from("127.0.0.3", "127.0.0.2", port) == 403  # source not allowed
    finally:
        proc.terminate()
        out = proc.communicate(timeout=10)[0]
    assert f"Listening on 127.0.0.1:{port}, 127.0.0.2:{port}" in out


def test_serve_refuses_every_interface(tmp_path):
    env = {
        **os.environ,
        "BOT_HOST": "127.0.0.1,0.0.0.0",
        "CRYPTO_HELPER_CONFIG": str(tmp_path / "e.env"),
    }
    (tmp_path / "e.env").touch()
    r = subprocess.run(
        [sys.executable, "-m", "app.cli", "serve"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 1 and "every network interface" in r.stderr
