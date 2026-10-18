"""Shared CLI plumbing: errors, settings, database access, output, subprocesses."""

import getpass
import os
import pwd
import shutil
import subprocess
import sys

from sqlalchemy import select

from app import migrate
from app.audit import record
from app.cli.layout import NAME, current_layout
from app.config import Settings
from app.db import make_engine, make_session_factory
from app.models import User
from app.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

PROG = NAME
# How CLI actions appear in the audit log. Not a valid username, so it can't be confused
# with a real account.
CLI_ACTOR = "<cli>"
CLI_SOURCE = "local-cli"


class CliError(Exception):
    """A problem to report to the user (exit code 1), not a crash."""


class UsageError(Exception):
    """The command was typed wrong (exit code 2); the message is the usage text."""


# ---- output ------------------------------------------------------------------------------

_TTY = sys.stdout.isatty()


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def ok(text: str) -> str:
    return paint(text, "32")


def warn(text: str) -> str:
    return paint(text, "33")


def bad(text: str) -> str:
    return paint(text, "31")


def dim(text: str) -> str:
    return paint(text, "2")


def step(text: str) -> None:
    print(f"{paint('==>', '36')} {text}", flush=True)


# ---- privileges --------------------------------------------------------------------------


def is_root() -> bool:
    return os.geteuid() == 0


def require_root(what: str) -> None:
    if not is_root():
        raise CliError(f"{what} needs root. Run it with sudo: sudo {PROG} ...")


def service_user_exists(user: str = NAME) -> bool:
    try:
        pwd.getpwnam(user)
        return True
    except KeyError:
        return False


def drop_to_service_user(user: str = NAME) -> bool:
    """When root on an installed system, become the service user.

    Then any file SQLite or a backup creates belongs to the service, and a bug in a
    command can't do more than the service itself could. Returns True if it switched.
    """
    if not is_root() or not current_layout().is_installed() or not service_user_exists(user):
        return False
    pw = pwd.getpwnam(user)
    os.initgroups(user, pw.pw_gid)
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    os.environ["HOME"] = pw.pw_dir
    return True


# ---- settings and database ---------------------------------------------------------------


def load_settings() -> Settings:
    """Config from $CRYPTO_HELPER_CONFIG, else the installed service's file, else ./.env."""
    explicit = os.environ.get("CRYPTO_HELPER_CONFIG")
    config = explicit or (str(current_layout().config) if current_layout().is_installed() else None)
    if config:
        try:
            with open(config):
                pass
        except PermissionError:
            raise CliError(f"Can't read {config}. Run it with sudo: sudo {PROG} ...") from None
        except FileNotFoundError:
            raise CliError(f"Config file {config} doesn't exist.") from None
        return Settings(_env_file=config)
    return Settings()


def open_db(settings: Settings, *, require_current: bool = True):
    engine = make_engine(settings.database_url)
    if require_current:
        current, head = migrate.current_revision(engine), migrate.head_revision()
        if current != head:
            raise CliError(
                f"The database is at revision {current or 'none'}, the code expects {head}. "
                f"Run `{PROG} db migrate` first."
            )
    return engine, make_session_factory(engine)


def find_user(db, name: str) -> User:
    user = db.scalar(select(User).where(User.username == name))
    if user is None:
        raise CliError(f"No account named {name!r}. See `{PROG} account list`.")
    return user


def audit(db, action: str, target: User, detail: str) -> None:
    record(
        db,
        action,
        user_id=None,
        username=CLI_ACTOR,
        detail=f"{target.username} (id {target.id}): {detail}",
        source_ip=CLI_SOURCE,
    )


def read_new_password(use_stdin: bool) -> str:
    if use_stdin:
        password = sys.stdin.read().rstrip("\r\n")
    else:
        if not sys.stdin.isatty():
            raise CliError("No terminal to ask for the password. Pipe it in with --stdin.")
        password = getpass.getpass("New password: ")
        if getpass.getpass("Repeat: ") != password:
            raise CliError("The passwords don't match. Nothing was changed.")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise CliError(
            f"Passwords must be {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters."
        )
    return password


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise CliError(f"{question} Re-run with --yes to confirm without a terminal.")
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


# ---- subprocesses ------------------------------------------------------------------------


# Admin tools (useradd, runuser, ...) live in sbin, which sudo/su shells don't always have.
SEARCH_PATH = os.pathsep.join([os.environ.get("PATH", ""), "/usr/local/sbin", "/usr/sbin", "/sbin"])


def which(cmd: str) -> str | None:
    return shutil.which(cmd, path=SEARCH_PATH)


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    user: str | None = None,
    cwd=None,
    umask: int = -1,
) -> subprocess.CompletedProcess:
    """Run a command (optionally as another user via runuser). Never through a shell."""
    if user:
        cmd = ["runuser", "-u", user, "--", *cmd]
    exe = cmd[0] if os.sep in cmd[0] else which(cmd[0])
    if exe is None:
        raise CliError(f"`{cmd[0]}` isn't installed or isn't on the PATH.")
    try:
        result = subprocess.run(
            [exe, *cmd[1:]], capture_output=capture, text=True, cwd=cwd, umask=umask
        )
    except OSError as e:
        raise CliError(f"Couldn't run `{cmd[0]}`: {e}") from None
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CliError(f"`{' '.join(cmd)}` failed (exit {result.returncode}): {detail}")
    return result
