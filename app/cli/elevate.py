"""Ask for sudo when a command needs root, instead of just failing.

The command re-runs itself through sudo with the same arguments, so you type your password
once at sudo's own prompt and carry on. `serve` is never elevated: systemd runs it as the
unprivileged service user, and it must stay that way.
"""

import os
import shutil
import sys

from app.cli.common import PROG, CliError, dim, service_user_exists
from app.cli.layout import NAME, current_layout

# Commands that manage the system: root every time.
ALWAYS_ROOT = {"service", "update", "embed"}
# Commands that read the installed service's config, key or database. Those files belong
# to root and the service user, so anyone else needs root once the service is installed.
ROOT_WHEN_INSTALLED = {"account", "setup", "db", "prices", "config", "doctor"}
NEVER = {"serve", "test", "version"}
# Settings that must survive sudo (which resets the environment).
PASS_THROUGH = ("CRYPTO_HELPER_CONFIG", "CRYPTO_HELPER_ROOT")
MARKER = "CRYPTO_HELPER_ELEVATED"


def _is_service_user() -> bool:
    if not service_user_exists(NAME):
        return False
    import pwd

    return os.geteuid() == pwd.getpwnam(NAME).pw_uid


def needs_root(command: str | None) -> bool:
    if command is None or command in NEVER or os.geteuid() == 0:
        return False
    if command in ALWAYS_ROOT:
        return True
    if command in ROOT_WHEN_INSTALLED:
        # The service user can already reach its own files (the backup timer runs as it).
        return current_layout().is_installed() and not _is_service_user()
    return False


def _self_command() -> list[str]:
    """How to run this same program again: the installed command, or python -m app.cli."""
    prog = sys.argv[0] if sys.argv else ""
    if prog.endswith("__main__.py") or not prog:
        return [sys.executable, "-m", "app.cli"]
    return [os.path.abspath(shutil.which(prog) or prog)]


def rerun_with_sudo(command: str, argv: list[str]) -> None:
    """Replace this process with `sudo <this command> <argv>`. Doesn't return."""
    if os.environ.get(MARKER):
        raise CliError("Still not running as root after sudo. Run it as root directly.")
    sudo = shutil.which("sudo")
    if sudo is None:
        raise CliError(
            f"`{command}` needs root and sudo isn't installed. Run it as root "
            f"(for example: su -c '{PROG} {' '.join(argv)}')."
        )
    keep = [f"{k}={os.environ[k]}" for k in PASS_THROUGH if os.environ.get(k)]
    print(
        dim(f"{PROG} {command} needs administrator rights; asking sudo..."),
        file=sys.stderr,
        flush=True,
    )
    cmd = [sudo, "--", "env", f"{MARKER}=1", *keep, *_self_command(), *argv]
    os.execv(sudo, cmd)
