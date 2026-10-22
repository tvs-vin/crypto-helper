"""The agent daemon (`crypto-helper agent run`, as root under systemd)."""

import json
import logging
import os
import re
import socket
import socketserver
import struct
import threading
import time

from pydantic import ValidationError

from app.agent.protocol import MAX_BYTES, RESTARTABLE, SWITCHABLE, Request, encode
from app.cli.common import CliError
from app.netconfig import REVERT_SECONDS

log = logging.getLogger("crypto-helper.agent")


class Refused(Exception):
    """A request the agent won't do; the message goes back to the caller."""


def peer_uid(sock: socket.socket) -> int:
    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


class Ops:
    """The operations. `system` and the embed helpers are module references so tests can
    swap systemctl for a recorder."""

    def __init__(self, layout, system, settings_loader, embed, run=None, start_terminal=None):
        self.layout = layout
        self.system = system
        self.load_settings = settings_loader
        self.embed = embed
        # How console commands run and terminals start: one-off systemd units in real life
        # (outside the agent's own sandbox); tests swap in local stand-ins.
        self.run = run or _run_unit
        self.start_terminal = start_terminal or _start_terminal_unit
        self.revert_seconds = REVERT_SECONDS
        self.min_confirm_seconds = 2.0  # the web UI restarts 0.5 s after a change
        self._revert_timer: threading.Timer | None = None
        self._revert_at = self._set_at = 0.0

    def units(self) -> dict[str, str]:
        from app.cli.service import AGENT, EMBED, SERVICE, TIMER

        return {"web": SERVICE, "embed": EMBED, "backups": TIMER, "agent": AGENT}

    def status(self, req: Request) -> dict:
        out = {}
        for name, unit in self.units().items():
            p = self.system.unit_properties(unit, "ActiveState", "UnitFileState")
            out[name] = {
                "active": p.get("ActiveState", "unknown"),
                "enabled": p.get("UnitFileState", "unknown"),
            }
        # For the health watcher: automatic restarts after a crash (a manual restart doesn't
        # count), and how the last backup run ended.
        for name in ("web", "embed"):
            n = self.system.unit_properties(self.units()[name], "NRestarts").get("NRestarts")
            out[name]["restarts"] = int(n) if n and n.isdigit() else 0
        from app.cli.layout import NAME

        result = self.system.unit_properties(f"{NAME}-backup.service", "Result").get("Result")
        out["backups"]["last_result"] = result or "unknown"
        s = self.load_settings()
        out["embed"]["configured"] = s.embed_enabled
        out["console"] = {"active": "on" if s.console_enabled else "off", "enabled": ""}
        out["terminal"] = {"active": "on" if s.terminal_enabled else "off", "enabled": ""}
        return {"services": out}

    def set(self, req: Request) -> dict:
        if req.service not in SWITCHABLE or req.on is None:
            raise Refused(f"can't switch {req.service!r} on or off from here")
        if req.service in ("console", "terminal"):
            from app.cli.embed import set_config

            key = f"BOT_{req.service.upper()}_ENABLED"
            set_config(self.layout.config, {key: "true" if req.on else "false"})
            return {"service": req.service, "on": req.on}
        if req.service == "embed":
            if req.on:
                s = self.load_settings().model_copy(update={"embed_enabled": True})
                self.embed.start(self.layout, {"BOT_EMBED_ENABLED": "true"}, s)
            else:
                self.embed.stop(self.layout)
        else:
            from app.cli.service import TIMER

            self.system.systemctl("enable" if req.on else "disable", "--now", "--quiet", TIMER)
        return {"service": req.service, "on": req.on}

    def restart(self, req: Request) -> dict:
        if req.service not in RESTARTABLE:
            raise Refused(f"can't restart {req.service!r} from here")
        unit = self.units()[req.service]
        if req.service == "embed" and not self.load_settings().embed_enabled:
            raise Refused("the embed server is off")
        if req.service == "web":
            # Answer first: restarting the web app ends the request that asked.
            def later():
                time.sleep(0.5)
                self.system.systemctl("restart", unit, check=False)

            threading.Thread(target=later, daemon=True).start()
            return {"service": "web", "restarting": True}
        self.system.systemctl("restart", unit)
        return {"service": req.service, "restarted": True}

    def backup(self, req: Request) -> dict:
        from app.cli.layout import NAME

        self.system.systemctl("start", "--no-block", f"{NAME}-backup.service")
        return {"started": True}

    def console(self, req: Request) -> dict:
        from app.agent import console

        if not self.load_settings().console_enabled:
            raise Refused("the Console is turned off (Services window)")
        if req.command is None:
            raise Refused("which command?")
        args = [str(self.layout.executable), *console.argv(req.command, req.lines)]
        code, output = self.run(args, console.TIMEOUT_SECONDS)
        if len(output) > console.MAX_OUTPUT:
            output = output[: console.MAX_OUTPUT] + "\n[output cut short]"
        return {"command": req.command, "exit_code": code, "output": output}

    def terminal(self, req: Request) -> dict:
        import secrets

        if not self.load_settings().terminal_enabled:
            raise Refused("the Terminal is turned off (Services window)")
        session = secrets.token_hex(16)
        path = os.path.join(
            os.path.dirname(self.load_settings().agent_socket), f"term-{session}.sock"
        )
        self.start_terminal(
            self.layout, session, path, req.cols or 100, req.rows or 30, req.client_ip
        )
        for _ in range(100):  # the session unit makes its socket as it starts
            if os.path.exists(path):
                return {"session": session, "socket": path}
            time.sleep(0.05)
        raise Refused("the terminal session didn't start")

    def update_check(self, req: Request) -> dict:
        """Is a newer version waiting? `crypto-helper update --check` (it needs the network, so
        it runs as a one-off unit like the Console's commands). Never installs anything."""
        code, output = self.run([str(self.layout.executable), "update", "--check"], 120)
        return parse_update_check(code, output)

    # ---- network (12a onboarding) -----------------------------------------------------------

    @property
    def revert_file(self):
        return self.layout.config.with_name("config.env.revert")

    def network_state(self, req: Request) -> dict:
        s = self.load_settings()
        timer = self._revert_timer
        left = max(0, round(self._revert_at - time.monotonic())) if timer else 0
        return {
            "hosts": s.host,
            "port": s.port,
            "allowed_networks": s.allowed_networks,
            "pending": self.revert_file.exists(),
            "seconds_left": left,
        }

    def network_set(self, req: Request) -> dict:
        from app import netconfig
        from app.cli.embed import set_config

        try:
            hosts, nets = netconfig.check(req.hosts or [], req.allowed_networks or [])
        except netconfig.NetConfigError as e:
            raise Refused(str(e)) from None
        if self.revert_file.exists():
            raise Refused("a network change is still waiting to be confirmed")
        old = self.layout.config.read_text()
        self.revert_file.touch(mode=0o600)
        self.revert_file.write_text(old)
        set_config(self.layout.config, netconfig.config_updates(hosts, nets))
        self._restart_listeners()
        self._set_at = time.monotonic()
        self._revert_at = self._set_at + self.revert_seconds
        self._revert_timer = threading.Timer(self.revert_seconds, self.revert)
        self._revert_timer.daemon = True
        self._revert_timer.start()
        return {"hosts": hosts, "allowed_networks": nets, "confirm_within": self.revert_seconds}

    def network_confirm(self, req: Request) -> dict:
        if not self.revert_file.exists():
            raise Refused("there's no network change to confirm")
        if time.monotonic() < self._set_at + self.min_confirm_seconds:
            # Only the restarted web UI may confirm (it proves the new settings work); the old
            # one is gone by now.
            raise Refused("too early: the web UI hasn't restarted yet")
        if self._revert_timer:
            self._revert_timer.cancel()
            self._revert_timer = None
        self.revert_file.unlink()
        return {"confirmed": True}

    def revert(self) -> bool:
        """Put the settings from before an unconfirmed change back. Also run at start-up: a
        change the agent can't vouch for (it restarted meanwhile) is undone."""
        self._revert_timer = None
        if not self.revert_file.exists():
            return False
        # In place (not a new file): keeps the config's owner and mode.
        self.layout.config.write_text(self.revert_file.read_text())
        self.revert_file.unlink()
        log.warning("agent: network change not confirmed in time: previous settings restored")
        self._restart_listeners()
        return True

    def _restart_listeners(self) -> None:
        """Restart the web UI (and the embed server, which may follow its addresses), after
        answering: the request that asked may be riding on the old addresses."""
        units = [self.units()["web"]]
        if self.load_settings().embed_enabled:
            units.append(self.units()["embed"])

        def later():
            time.sleep(0.5)
            for unit in units:
                self.system.systemctl("restart", unit, check=False)

        threading.Thread(target=later, daemon=True).start()

    def handle(self, req: Request) -> dict:
        return {
            "network.state": self.network_state,
            "network.set": self.network_set,
            "network.confirm": self.network_confirm,
            "status": self.status,
            "service.set": self.set,
            "service.restart": self.restart,
            "backup.run": self.backup,
            "console.run": self.console,
            "terminal.open": self.terminal,
            "update.check": self.update_check,
        }[req.op](req)


def parse_update_check(code: int, output: str) -> dict:
    """{"available": bool, "commits": n, "newest": "<hash> <subject>" | None} from the output of
    `crypto-helper update --check`."""
    if code == 0 and "Already up to date" in output:
        return {"available": False, "commits": 0, "newest": None}
    commits = [ln.strip() for ln in output.splitlines() if re.match(r"^[0-9a-f]{7,40} \S", ln)]
    if code == 0 and commits:
        return {"available": True, "commits": len(commits), "newest": commits[0][:120]}
    last = next((ln.strip() for ln in reversed(output.splitlines()) if ln.strip()), "no output")
    raise Refused(f"couldn't check for updates: {last[:200]}")


MUTATING = {"service.set", "service.restart", "backup.run", "network.set", "network.confirm"}


def _same_config() -> list[str]:
    """One-off units use the agent's own config file (systemd doesn't pass it on)."""
    path = os.environ.get("CRYPTO_HELPER_CONFIG")
    return [f"--setenv=CRYPTO_HELPER_CONFIG={path}"] if path else []


def _same_home() -> list[str]:
    """One-off units start with no HOME, so git (`update --check`) can't find the credentials a
    private repository needs. Give them the agent's own: the same root account `sudo
    crypto-helper update` runs as, so nothing is reachable that wasn't already."""
    import pwd

    return [f"--setenv=HOME={pwd.getpwuid(os.getuid()).pw_dir}"]


def _run_unit(args: list[str], timeout: int) -> tuple[int, str]:
    """Run a command as a one-off systemd unit and capture its output. It runs outside the
    agent's sandbox (so it has the network, e.g. for `prices check`), with a time limit."""
    import secrets
    import subprocess

    unit = f"crypto-helper-console-{secrets.token_hex(4)}"
    cmd = [
        "systemd-run", "--wait", "--pipe", "--quiet", "--collect", "--service-type=exec",
        f"--unit={unit}", f"--property=RuntimeMaxSec={timeout}",
        "--setenv=NO_COLOR=1", "--setenv=TERM=dumb", *_same_config(), *_same_home(), *args,
    ]  # fmt: skip
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        return 124, "Timed out."
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


def _start_terminal_unit(layout, session: str, path: str, cols: int, rows: int, host) -> None:
    """Start the login session as its own unit: not sandboxed, because a real login session
    (switching user, sudo) needs root's full powers; the agent itself keeps none."""
    import subprocess

    cmd = [
        "systemd-run", "--quiet", "--collect", "--service-type=exec",
        f"--unit=crypto-helper-terminal-{session[:12]}",
        "--description=Crypto Helper terminal session", *_same_config(),
        str(layout.executable), "agent", "terminal-bridge", "--socket", path,
        "--cols", str(cols), "--rows", str(rows),
        *(["--host", host] if host else []),
    ]  # fmt: skip
    subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=True)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        server: AgentServer = self.server  # type: ignore[assignment]
        self.request.settimeout(10)
        try:
            uid = peer_uid(self.request)
        except OSError:
            return
        if uid not in server.allowed_uids:
            log.warning("agent: refused a connection from uid %s", uid)
            self._send({"ok": False, "error": "not allowed"})
            return
        try:
            line = self.rfile.readline(MAX_BYTES + 1)
        except (TimeoutError, OSError):
            return
        if len(line) > MAX_BYTES or not line.endswith(b"\n"):
            self._send({"ok": False, "error": "request too large or incomplete"})
            return
        try:
            req = Request(**json.loads(line))
        except (ValueError, TypeError, ValidationError):
            self._send({"ok": False, "error": "not a request the agent understands"})
            return
        what = f"{req.actor}: {req.op}" + (f" {req.service}" if req.service else "")
        what += "" if req.on is None else (" on" if req.on else " off")
        try:
            if req.op in MUTATING:
                with server.lock:  # one change at a time
                    result = server.ops.handle(req)
            else:  # reads, console commands and terminals don't block each other
                result = server.ops.handle(req)
        except (Refused, CliError) as e:
            log.warning("agent: %s refused: %s", what, e)
            self._send({"ok": False, "error": str(e)})
            return
        except Exception as e:  # report, keep serving
            log.exception("agent: %s failed", what)
            self._send({"ok": False, "error": f"failed: {type(e).__name__}"})
            return
        if req.op != "status":
            log.info("agent: %s", what)
        self._send({"ok": True, **result})

    def _send(self, obj: dict) -> None:
        try:
            self.wfile.write(encode(obj))
        except OSError:
            pass


class AgentServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, allowed_uids: set[int], ops: Ops):
        self.allowed_uids = allowed_uids
        self.ops = ops
        self.lock = threading.Lock()
        if os.path.exists(path):  # a stale socket from a previous run
            os.unlink(path)
        super().__init__(path, _Handler)
        # Owner root, group = the unit's Group (the service user's group): only those two
        # can connect at all. SO_PEERCRED then checks the actual user on every connection.
        os.chmod(path, 0o660)
