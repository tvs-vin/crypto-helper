"""7c: the terminal bridge (a real pty), the agent's console/terminal operations, and the
Console and Terminal API including the WebSocket. A shell stands in for `login` here; the
real login prompt is checked on the VM."""

import os
import socket
import struct
import tempfile
import threading
import time
import types

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.agent import terminal as term
from app.agent.client import AgentError, call
from app.agent.server import AgentServer, Ops
from app.cli.layout import Layout
from app.config import Settings
from app.main import create_app
from tests.conftest import PASSWORD, H
from tests.test_agent import FakeEmbed, FakeSystem
from tests.test_totp import code, enrol
from tests.test_users import PW2
from tests.wallet_helpers import user_with

SHELL = ["/bin/sh", "-c", "PATH=/usr/bin:/bin; export PATH; PS1='$ '; export PS1; exec /bin/sh -i"]


def short_path() -> str:
    return os.path.join(tempfile.mkdtemp(prefix="t-"), "term-" + "a" * 32 + ".sock")


def start_bridge(path, cols=100, rows=30, allowed=None, command=SHELL):
    t = threading.Thread(
        target=term.run_bridge,
        args=(path, cols, rows, None, allowed or {os.getuid()}, None, command),
        daemon=True,
    )
    t.start()
    for _ in range(100):
        if os.path.exists(path):
            return t
        time.sleep(0.02)
    raise AssertionError("bridge socket didn't appear")


def read_until(sock, needle: bytes, timeout=5) -> bytes:
    reader, out, end = term.FrameReader(), b"", time.time() + timeout
    sock.settimeout(0.2)
    while time.time() < end:
        try:
            data = sock.recv(65536)
        except TimeoutError:
            continue
        if not data:
            break
        for kind, payload in reader.feed(data):
            if kind == term.DATA:
                out += payload
            elif kind == term.EXIT:
                return out + b"<EXIT>"
        if needle in out:
            return out
    return out


# ---- the bridge ------------------------------------------------------------------------------


def test_bridge_runs_a_session_on_a_pty_with_resizes():
    path = short_path()
    start_bridge(path, cols=100, rows=30)
    assert os.stat(path).st_mode & 0o777 == 0o660
    s = socket.socket(socket.AF_UNIX)
    s.connect(path)
    time.sleep(0.2)
    assert not os.path.exists(path)  # one connection only: the socket is gone
    s.sendall(term.frame(term.DATA, b"stty size\n"))
    assert b"30 100" in read_until(s, b"30 100")
    s.sendall(term.frame(term.RESIZE, struct.pack(">HH", 120, 40)))
    s.sendall(term.frame(term.DATA, b"stty size\n"))
    assert b"40 120" in read_until(s, b"40 120")
    s.sendall(term.frame(term.DATA, b"exit\n"))
    assert read_until(s, b"<EXIT>").endswith(b"<EXIT>")
    s.close()


def test_closing_the_connection_ends_the_session():
    path = short_path()
    t = start_bridge(path, command=["/bin/sh", "-c", "echo $$ > " + path + ".pid; exec sleep 60"])
    s = socket.socket(socket.AF_UNIX)
    s.connect(path)
    for _ in range(50):
        if os.path.exists(path + ".pid"):
            break
        time.sleep(0.05)
    pid = int(open(path + ".pid").read())
    s.close()
    t.join(5)
    assert not t.is_alive()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_bridge_refuses_other_users_and_gives_up(monkeypatch):
    monkeypatch.setattr(term, "ACCEPT_SECONDS", 1)
    path = short_path()
    t = start_bridge(path, allowed={12345})
    s = socket.socket(socket.AF_UNIX)
    s.connect(path)
    s.settimeout(2)
    try:  # closed straight away (a clean close or, under load, a reset)
        assert s.recv(10) == b""
    except ConnectionResetError:
        pass
    t.join(3)
    assert not t.is_alive() and not os.path.exists(path)


def test_bad_frames_end_the_session():
    path = short_path()
    t = start_bridge(path)
    s = socket.socket(socket.AF_UNIX)
    s.connect(path)
    s.sendall(struct.pack(">BI", 9, 3) + b"abc")
    assert read_until(s, b"<EXIT>").endswith(b"<EXIT>")
    t.join(5)
    assert not t.is_alive()


# NEVER name real system files in these tests: they run as root, and a broken check (or a
# mutation test switching one off) would then act on the real file. That's how /etc/passwd
# was once lost on the owner's VM. Stand-ins in a temp folder only.
@pytest.mark.parametrize("name", ["passwd", "agent.sock", "term-x.sock"])
def test_bridge_cli_only_takes_session_sockets(name, tmp_path, monkeypatch, capsys):
    from app.cli import main

    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    monkeypatch.setenv("BOT_AGENT_SOCKET", str(agent_dir / "agent.sock"))
    target = (tmp_path / name) if name == "passwd" else (agent_dir / name)
    target.write_text("precious\n")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert main(["agent", "terminal-bridge", "--socket", str(target)]) == 1
    assert "Not a terminal session socket" in capsys.readouterr().err
    assert target.read_text() == "precious\n"


def test_bridge_never_replaces_or_deletes_an_existing_file(tmp_path):
    """Even handed a path that exists (a check bypassed), the bridge leaves it alone."""
    target = tmp_path / "term-precious.sock"
    target.write_text("precious\n")
    with pytest.raises(FileExistsError):
        term.accept_one(str(target), {os.getuid()}, None)
    assert target.read_text() == "precious\n"
    assert list(tmp_path.iterdir()) == [target]  # no temporary file left either


# ---- the agent's console and terminal --------------------------------------------------------


@pytest.fixture
def shell_agent(tmp_path):
    folder = tempfile.mkdtemp(prefix="ag-")
    path = os.path.join(folder, "a.sock")
    flags = {"console_enabled": True, "terminal_enabled": True}
    ran = []

    def run(args, timeout):
        ran.append(args)
        return 0, "All good.\n"

    def start(layout, session, sock, cols, rows, host):
        start_bridge(sock, cols, rows)

    layout = Layout(root=tmp_path, user="root")
    layout.etc.mkdir(parents=True)
    layout.config.write_text("BOT_HOST=127.0.0.1\n")

    def settings():
        return Settings(_env_file=None, agent_socket=path, **flags)

    ops = Ops(layout, FakeSystem(), settings, FakeEmbed(), run=run, start_terminal=start)
    server = AgentServer(path, {os.getuid()}, ops)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield types.SimpleNamespace(path=path, flags=flags, ran=ran, layout=layout)
    server.shutdown()
    server.server_close()


def test_console_runs_only_known_commands(shell_agent):
    r = call(shell_agent.path, "console.run", "a", command="logs", lines=50)
    assert r["output"] == "All good.\n" and r["exit_code"] == 0
    assert shell_agent.ran[-1][1:] == ["service", "logs", "-n", "50"]
    assert shell_agent.ran[-1][0].endswith("/venv/bin/crypto-helper")
    # Refused by the request schema itself (not just a failed lookup later on).
    with pytest.raises(AgentError, match="not a request the agent understands"):
        call(shell_agent.path, "console.run", "a", command="service uninstall --purge")


def test_console_and_terminal_refused_while_off(shell_agent):
    shell_agent.flags.update(console_enabled=False, terminal_enabled=False)
    with pytest.raises(AgentError, match="Console is turned off"):
        call(shell_agent.path, "console.run", "a", command="status")
    with pytest.raises(AgentError, match="Terminal is turned off"):
        call(shell_agent.path, "terminal.open", "a", cols=80, rows=24)
    assert shell_agent.ran == []


def test_switching_console_and_terminal_writes_the_config(shell_agent):
    call(shell_agent.path, "service.set", "a", service="terminal", on=True)
    call(shell_agent.path, "service.set", "a", service="console", on=False)
    text = shell_agent.layout.config.read_text()
    assert "BOT_TERMINAL_ENABLED=true" in text and "BOT_CONSOLE_ENABLED=false" in text


def test_terminal_open_returns_a_fresh_session_socket(shell_agent):
    r = call(shell_agent.path, "terminal.open", "a", cols=80, rows=24, client_ip="100.64.0.5")
    assert os.path.basename(r["socket"]) == f"term-{r['session']}.sock"
    assert os.path.dirname(r["socket"]) == os.path.dirname(shell_agent.path)
    with pytest.raises(AgentError):
        call(shell_agent.path, "terminal.open", "a", client_ip="100.64.0.5; reboot")


# ---- the web side ----------------------------------------------------------------------------


@pytest.fixture
def web(shell_agent, tmp_path):
    a = create_app(
        Settings(
            database_url="sqlite://",
            price_provider="mock",
            agent_socket=shell_agent.path,
            state_dir=str(tmp_path / "state"),
            _env_file=None,
        )
    )
    c = TestClient(a)
    c.__enter__()
    c.post("/api/setup", json={"token": a.state.setup_token, "password": PASSWORD}, headers=H)
    c.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
    yield types.SimpleNamespace(app=a, admin=c)
    c.__exit__(None, None, None)


def open_terminal(c, secret, password=PASSWORD, step=1):
    return c.post(
        "/api/terminal/open",
        json={"password": password, "code": code(secret, step), "cols": 90, "rows": 25},
        headers=H,
    )


def test_console_needs_permission_and_2fa(web):
    viewer = user_with(web.app, web.admin, "viewer", ["wallets.view"])
    assert viewer.post("/api/console/run", json={"command": "status"}, headers=H).status_code == 403
    r = web.admin.post("/api/console/run", json={"command": "status"}, headers=H)
    assert r.status_code == 403 and "two-factor" in r.json()["detail"]
    enrol(web.admin)
    r = web.admin.post("/api/console/run", json={"command": "status"}, headers=H)
    assert r.status_code == 200 and r.json()["output"] == "All good.\n"
    assert web.admin.post("/api/console/run", json={"command": "rm"}, headers=H).status_code == 422
    entry = web.admin.get("/api/audit?limit=1").json()[0]
    assert entry["action"] == "console.run" and entry["detail"] == "status: exit 0"


def test_only_super_grants_terminal_access(web):
    admin = user_with(
        web.app, web.admin, "admin1", ["users.manage", "terminal.use", "wallets.view"]
    )
    r = admin.post(
        "/api/users",
        json={"username": "bob", "password": "bob-password-123", "permissions": ["terminal.use"]},
        headers=H,
    )
    assert r.status_code == 403 and "Only super" in r.json()["detail"]
    r = admin.post(
        "/api/users",
        json={"username": "bob", "password": "bob-password-123", "permissions": ["wallets.view"]},
        headers=H,
    )
    bob = r.json()["id"]
    r = admin.patch(
        f"/api/users/{bob}", json={"permissions": ["wallets.view", "terminal.use"]}, headers=H
    )
    assert r.status_code == 403


def test_terminal_open_checks(web):
    r = web.admin.post(
        "/api/terminal/open", json={"password": PASSWORD, "code": "123456"}, headers=H
    )
    assert r.status_code == 403 and "two-factor" in r.json()["detail"]
    secret, recovery = enrol(web.admin)
    assert open_terminal(web.admin, secret, password="wrong-password").status_code == 403
    r = web.admin.post(
        "/api/terminal/open", json={"password": PASSWORD, "code": recovery[0]}, headers=H
    )
    # Recovery codes don't open terminals: refused by shape (longer than a 6-8 digit code)
    # before anything else; the code check then only accepts authenticator codes anyway.
    assert r.status_code == 422
    admin = user_with(web.app, web.admin, "admin2", ["users.manage"])
    r = open_terminal(web.admin, secret)
    assert r.status_code == 200 and r.json()["ticket"]
    seen = admin.get("/api/notifications").json()["items"]
    assert [n["title"] for n in seen] == ["super opened a terminal"]  # other admins are told
    assert open_terminal(web.admin, secret).status_code == 403  # same code again: replay
    actions = [e["action"] for e in web.admin.get("/api/audit?limit=10").json()]
    assert actions.count("terminal.fail") >= 2 and "terminal.open" in actions


def test_terminal_websocket_end_to_end(web):
    secret, _ = enrol(web.admin)
    ticket = open_terminal(web.admin, secret).json()["ticket"]
    with web.admin.websocket_connect(
        f"/api/terminal/ws?ticket={ticket}", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_bytes(b"stty size\n")
        out = b""
        while b"25 90" not in out:
            out += ws.receive_bytes()
        ws.send_text('{"resize": [132, 43]}')
        ws.send_bytes(b"stty size\n")
        while b"43 132" not in out:
            out += ws.receive_bytes()
    # The ticket worked once only.
    with pytest.raises(WebSocketDisconnect) as e:
        with web.admin.websocket_connect(
            f"/api/terminal/ws?ticket={ticket}", headers={"origin": "http://testserver"}
        ) as ws:
            ws.receive_bytes()
    assert e.value.code == 4401
    for _ in range(100):
        actions = [x["action"] for x in web.admin.get("/api/audit?limit=5").json()]
        if "terminal.close" in actions:
            break
        time.sleep(0.05)
    assert "terminal.close" in actions


@pytest.mark.parametrize(
    "headers, ticket_ok, expected",
    [
        ({"origin": "http://evil.example.com"}, True, 4403),
        ({}, True, 4403),  # no Origin
        ({"origin": "http://testserver"}, False, 4401),
    ],
)
def test_terminal_websocket_refusals(web, headers, ticket_ok, expected):
    secret, _ = enrol(web.admin)
    ticket = open_terminal(web.admin, secret).json()["ticket"] if ticket_ok else "made-up"
    with pytest.raises(WebSocketDisconnect) as e:
        with web.admin.websocket_connect(
            f"/api/terminal/ws?ticket={ticket}", headers=headers
        ) as ws:
            ws.receive_bytes()
    assert e.value.code == expected


def test_ticket_belongs_to_its_session(web):
    secret, _ = enrol(web.admin)
    ticket = open_terminal(web.admin, secret).json()["ticket"]
    other = TestClient(web.app)  # no session cookie
    with pytest.raises(WebSocketDisconnect) as e:
        with other.websocket_connect(
            f"/api/terminal/ws?ticket={ticket}", headers={"origin": "http://testserver"}
        ) as ws:
            ws.receive_bytes()
    assert e.value.code == 4401


def test_ticket_only_works_for_the_session_that_asked(web):
    """Another signed-in account (its own valid session) can't use someone else's ticket."""
    secret, _ = enrol(web.admin)
    ticket = open_terminal(web.admin, secret).json()["ticket"]
    other = user_with(web.app, web.admin, "someone", ["terminal.use"])
    with pytest.raises(WebSocketDisconnect) as e:
        with other.websocket_connect(
            f"/api/terminal/ws?ticket={ticket}", headers={"origin": "http://testserver"}
        ) as ws:
            ws.receive_bytes()
    assert e.value.code == 4401


def test_terminal_opens_are_limited_per_hour(web, monkeypatch):
    from app.routers import shell

    monkeypatch.setattr(shell, "OPENS_PER_HOUR", 2)
    # Each open needs a fresh code; accept any here (the code check has its own test).
    monkeypatch.setattr(shell.totp, "verify_totp", lambda secret, c, last: (last or 0) + 1)
    secret, _ = enrol(web.admin)
    assert open_terminal(web.admin, secret, step=1).status_code == 200
    assert open_terminal(web.admin, secret, step=2).status_code == 200
    r = open_terminal(web.admin, secret, step=3)
    assert r.status_code == 429


@pytest.mark.parametrize("how", ["sign out", "permission taken away", "new password required"])
def test_terminal_closes_when_access_ends(web, monkeypatch, how):
    from app.routers import shell

    monkeypatch.setattr(shell, "RECHECK_SECONDS", 0.2)
    op = user_with(web.app, web.admin, "operator", ["terminal.use"])  # its own browser
    secret, _ = enrol(op, PW2)
    ticket = open_terminal(op, secret, password=PW2).json()["ticket"]
    with op.websocket_connect(
        f"/api/terminal/ws?ticket={ticket}", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_bytes(b"echo still-here\n")
        out = b""
        while b"still-here" not in out:
            out += ws.receive_bytes()
        if how == "sign out":
            op.post("/api/auth/logout", headers=H)
        else:
            uid = next(
                u["id"] for u in web.admin.get("/api/users").json() if u["username"] == "operator"
            )
            change = (
                {"permissions": []}
                if how == "permission taken away"
                else {"must_change_password": True}
            )
            web.admin.patch(f"/api/users/{uid}", json=change, headers=H)
        # The next check (0.2 s) ends it. Wait in a thread with a deadline: if the check
        # were broken, receiving would block forever (a hang, not a failure).
        ended = threading.Event()

        def drain():
            try:
                while True:
                    ws.receive_bytes()
            except WebSocketDisconnect:
                ended.set()

        threading.Thread(target=drain, daemon=True).start()
        assert ended.wait(5), "the terminal stayed open after access ended"


def test_bridge_only_removes_its_own_socket(tmp_path, monkeypatch):
    """If something else ends up at the path while the bridge waits, it isn't deleted."""
    monkeypatch.setattr(term, "ACCEPT_SECONDS", 1)
    path = tmp_path / "term-x.sock"
    t = threading.Thread(target=term.accept_one, args=(str(path), {os.getuid()}, None))
    t.start()
    for _ in range(50):
        if path.exists():
            break
        time.sleep(0.02)
    path.unlink()
    path.write_text("someone else's\n")  # not the bridge's socket any more
    t.join(5)
    assert path.read_text() == "someone else's\n"
