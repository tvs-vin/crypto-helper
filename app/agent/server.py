"""The agent daemon (`crypto-helper agent run`, as root under systemd)."""

import json
import logging
import os
import socket
import socketserver
import struct
import threading
import time

from pydantic import ValidationError

from app.agent.protocol import MAX_BYTES, RESTARTABLE, SWITCHABLE, Request, encode
from app.cli.common import CliError

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

    def __init__(self, layout, system, settings_loader, embed):
        self.layout = layout
        self.system = system
        self.load_settings = settings_loader
        self.embed = embed

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
        out["embed"]["configured"] = self.load_settings().embed_enabled
        return {"services": out}

    def set(self, req: Request) -> dict:
        if req.service not in SWITCHABLE or req.on is None:
            raise Refused(f"can't switch {req.service!r} on or off from here")
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

    def handle(self, req: Request) -> dict:
        return {
            "status": self.status,
            "service.set": self.set,
            "service.restart": self.restart,
            "backup.run": self.backup,
        }[req.op](req)


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
            with server.lock:  # one change at a time
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
