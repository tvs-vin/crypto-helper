"""Small wrappers around the OS so service/update/doctor logic can be tested with fakes."""

import grp
import json
import os
import pwd
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.cli.common import CliError, run, which


def write_file(
    path: Path,
    content: str,
    mode: int,
    owner: str = "root",
    group: str = "root",
    *,
    exclusive: bool = False,
) -> None:
    """Write with the final mode from the first byte (no window where it's readable)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, mode)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.chmod(path, mode)  # O_CREAT's mode is ignored for an existing file
    chown(path, owner, group)


def chown(path: Path, owner: str, group: str) -> None:
    os.chown(path, pwd.getpwnam(owner).pw_uid, grp.getgrnam(group).gr_gid)


def ensure_dir(path: Path, mode: int, owner: str, group: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    chown(path, owner, group)


USER_COMMENT = "Crypto Helper service"  # uninstall only deletes an account with this comment


def ensure_system_user(name: str, home: Path) -> bool:
    """Create a locked system account with no shell. True if it was created."""
    try:
        pwd.getpwnam(name)
        return False
    except KeyError:
        pass
    run(
        [
            "useradd",
            "--system",
            "--user-group",
            "--home-dir",
            str(home),
            "--no-create-home",
            "--shell",
            "/usr/sbin/nologin",
            "--comment",
            USER_COMMENT,
            name,
        ]
    )
    return True


def have(cmd: str) -> bool:
    return which(cmd) is not None


def systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run(["systemctl", *args], check=check)


def unit_properties(unit: str, *props: str) -> dict[str, str]:
    out = systemctl("show", unit, *[f"--property={p}" for p in props], check=False).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_get(url: str, timeout: float = 3) -> tuple[int, dict, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode()


def wait_healthy(host: str, port: int, timeout: float = 30) -> dict | None:
    """Poll the setup-status endpoint until it answers. Returns its JSON, or None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _, body = http_get(f"http://{host}:{port}/api/setup/status", timeout=2)
            if status == 200:
                return json.loads(body)
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    return None


def journal_tail(unit: str, lines: int = 25) -> str:
    if not have("journalctl"):
        return ""
    return run(
        ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "cat"], check=False
    ).stdout


def require_systemd() -> None:
    if not have("systemctl") or not Path("/run/systemd/system").exists():
        raise CliError("systemd isn't running on this machine, so the service can't be managed.")
