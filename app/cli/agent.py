"""`crypto-helper agent enable|disable|status|run`: the root helper behind the Services window."""

import logging
import pwd
import time

from app.cli import system
from app.cli.common import PROG, CliError, dim, load_settings, ok, require_root, step, warn
from app.cli.layout import current_layout
from app.cli.service import AGENT, write_units


def run() -> int:
    """The daemon itself (systemd starts it as root)."""
    require_root("The agent")
    from app.agent.server import AgentServer, Ops
    from app.cli import embed

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    layout = current_layout()
    settings = load_settings()
    try:
        allowed = {0, pwd.getpwnam(layout.user).pw_uid}
    except KeyError:
        raise CliError(f"The service user {layout.user} doesn't exist.") from None
    ops = Ops(layout, system, load_settings, embed)
    server = AgentServer(settings.agent_socket, allowed, ops)
    print(f"Agent listening on {settings.agent_socket}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def ping(timeout: float = 5) -> dict | None:
    from app.agent.client import AgentError, AgentUnavailable, call

    try:
        return call(load_settings().agent_socket, "status", "<cli>", timeout=timeout)
    except (AgentUnavailable, AgentError):
        return None


def agent(action: str) -> int:
    if action == "run":
        return run()
    require_root(f"`agent {action}`")
    layout = current_layout()
    if not layout.is_installed():
        raise CliError(f"The service isn't installed. Run: sudo {PROG} service install")
    if action == "status":
        p = system.unit_properties(AGENT, "ActiveState", "UnitFileState")
        answer = ping()
        print(
            f"Agent: {ok('running') if answer else warn(p.get('ActiveState', '?'))}; "
            f"at boot: {p.get('UnitFileState', '?')}"
        )
        if answer:
            for name, s in answer["services"].items():
                print(f"  {name:8} {s['active']:10} {dim(s['enabled'])}")
        return 0
    if action == "disable":
        system.systemctl("disable", "--now", "--quiet", AGENT, check=False)
        print(ok("Agent off.") + " The Services window can show settings but not change services.")
        return 0
    step("Writing the unit and starting the agent")
    write_units(layout)
    system.systemctl("daemon-reload")
    system.systemctl("enable", "--now", "--quiet", AGENT)
    system.systemctl("restart", AGENT)
    for _ in range(40):
        if ping(timeout=1):
            break
        time.sleep(0.25)
    else:
        print(system.journal_tail(AGENT))
        raise CliError("The agent didn't answer; see the log above.")
    print(ok("Agent on.") + " The Services window can now turn services on and off.")
    print(
        dim(
            "  It only does a fixed list of jobs for Crypto Helper's own services, and only "
            "for the web app. Turn it off any time: sudo crypto-helper agent disable"
        )
    )
    return 0


def terminal_bridge(path: str, cols: int, rows: int, host: str | None) -> int:
    """One terminal session: started by the agent as its own unit (see app/agent/terminal.py)."""
    import ipaddress
    import os

    from app.agent.terminal import run_bridge

    require_root("A terminal session")
    layout = current_layout()
    folder = os.path.dirname(load_settings().agent_socket)
    name = os.path.basename(path)
    # Only a fresh session socket in the agent's own folder, never any other path.
    if os.path.dirname(path) != folder or not (
        name.startswith("term-") and name.endswith(".sock") and len(name) == 42
    ):
        raise CliError("Not a terminal session socket.")
    if host:
        ipaddress.ip_address(host)
    user = pwd.getpwnam(layout.user)
    return run_bridge(path, cols, rows, host, {0, user.pw_uid}, user.pw_gid)
