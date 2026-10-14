"""`crypto-helper`: the command-line tool for running and administering the server.

Commands are noun first, then the thing, then the verb, e.g.
    crypto-helper account super password
Account commands work directly on the database, so they need to run on the VM itself
with access to the config and data files. That access is the root of trust: it's the
only way to change the `super` account.
"""

import argparse
import getpass
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app import accounts, migrate
from app.audit import record
from app.config import Settings
from app.db import make_engine, make_session_factory
from app.deps import effective_permissions
from app.models import User
from app.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.setup_token import read_setup_token
from app.timeutil import utcnow

PROG = "crypto-helper"
# How CLI actions appear in the audit log. Not a valid username, so it can't be confused
# with a real account.
CLI_ACTOR = "<cli>"
CLI_SOURCE = "local-cli"
SYSTEM_CONFIG = Path("/etc/crypto-helper/config.env")

ACCOUNT_USAGE = f"""usage:
  {PROG} account list
  {PROG} account <name> password [--stdin]   set a new password (asked for, never an argument)
  {PROG} account <name> unlock               clear a login lockout
  {PROG} account <name> 2fa reset            turn off 2FA and delete recovery codes
  {PROG} account <name> sessions revoke      sign the account out everywhere"""


class CliError(Exception):
    """A problem to report to the user (exit code 1), not a crash."""


class UsageError(Exception):
    """The command was typed wrong (exit code 2); the message is the usage text."""


# ---- shared plumbing ---------------------------------------------------------------------


def load_settings() -> Settings:
    """Config from $CRYPTO_HELPER_CONFIG, else the installed service's file, else ./.env."""
    explicit = os.environ.get("CRYPTO_HELPER_CONFIG")
    if explicit:
        return Settings(_env_file=explicit)
    if SYSTEM_CONFIG.exists():
        return Settings(_env_file=str(SYSTEM_CONFIG))
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


# ---- account -----------------------------------------------------------------------------


def account_list(settings: Settings) -> None:
    _, factory = open_db(settings)
    now = utcnow()
    with factory() as db:
        users = db.scalars(select(User).order_by(User.id)).all()
        rows = [("ID", "USERNAME", "ACTIVE", "2FA", "LOCKED", "PERMISSIONS")]
        for u in users:
            perms = "ALL (super)" if u.is_super else ", ".join(sorted(effective_permissions(u)))
            locked = u.locked_until is not None and u.locked_until > now
            rows.append(
                (
                    str(u.id),
                    u.username,
                    "yes" if u.is_active else "no",
                    "on" if u.totp_enabled else "off",
                    "yes" if locked else "no",
                    perms or "-",
                )
            )
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)) + "  " + r[-1])


def account_action(settings: Settings, name: str, words: list[str]) -> None:
    action = " ".join(w for w in words if not w.startswith("-"))
    flags = [w for w in words if w.startswith("-")]
    allowed_flags = {"password": {"--stdin"}}.get(action, set())
    if action not in ("password", "unlock", "2fa reset", "sessions revoke") or (
        set(flags) - allowed_flags
    ):
        raise UsageError(ACCOUNT_USAGE)

    password = read_new_password("--stdin" in flags) if action == "password" else None
    _, factory = open_db(settings)
    with factory() as db:
        user = find_user(db, name)
        if action == "password":
            accounts.set_password(user, password)
            n = accounts.revoke_sessions(db, user)
            audit(db, "user.update", user, f"password reset; {n} sessions revoked")
            msg = f"Password changed for {name}. {n} session(s) signed out."
        elif action == "unlock":
            accounts.unlock(user)
            audit(db, "user.update", user, "unlocked")
            msg = f"{name} is unlocked."
        elif action == "2fa reset":
            if not user.totp_enabled and not user.totp_secret:
                raise CliError(f"{name} doesn't have 2FA set up. Nothing to reset.")
            accounts.reset_2fa(db, user)
            n = accounts.revoke_sessions(db, user)
            audit(db, "2fa.reset", user, f"2FA and recovery codes removed; {n} sessions revoked")
            msg = (
                f"2FA is off for {name} and their recovery codes are deleted. "
                f"{n} session(s) signed out. They can set 2FA up again after logging in."
            )
        else:  # sessions revoke
            n = accounts.revoke_sessions(db, user)
            audit(db, "user.update", user, f"{n} sessions revoked")
            msg = f"{n} session(s) signed out for {name}."
        db.commit()
    print(msg)


# ---- setup / db --------------------------------------------------------------------------


def setup_token(settings: Settings) -> None:
    engine, factory = open_db(settings, require_current=False)
    if migrate.current_revision(engine) is not None:  # no tables yet = server never started
        with factory() as db:
            if db.scalar(select(User.id).limit(1)) is not None:
                raise CliError("Setup is already done: the super account exists.")
    token = read_setup_token(settings)
    if token is None:
        raise CliError("No setup token yet. Start the server: it creates one on first launch.")
    print(token)


def db_migrate(settings: Settings) -> None:
    engine = make_engine(settings.database_url)
    before, after = migrate.upgrade(engine)
    if before == after:
        print(f"Database is up to date (revision {after}).")
    else:
        print(f"Database migrated: {before or 'empty'} -> {after}.")


def db_backup(settings: Settings, target: str | None) -> None:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise CliError("Backups are only supported for SQLite databases.")
    source = Path(url.removeprefix("sqlite:///"))
    if not source.exists():
        raise CliError(f"Database file {source} doesn't exist.")
    if target:
        dest = Path(target)
    else:
        backups = Path(settings.state_dir) / "backups"
        backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest = backups / f"bot-{datetime.now():%Y%m%d-%H%M%S}.db"
    if dest.exists():
        raise CliError(f"{dest} already exists. Choose another path.")
    # The backup holds password hashes and encrypted secrets: private from the first byte.
    os.close(os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    # SQLite's online backup API copies a consistent snapshot even while the server runs.
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    print(f"Backup written to {dest}")
    print(
        "Note: 2FA secrets in it can only be read with the same secret key, so back up "
        "the key file too (separately)."
    )


# ---- entry point -------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Run and administer the Crypto Helper server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Run `{PROG} <command> --help` for details. Docs: WIKI/reference/cli.md",
    )
    sub = p.add_subparsers(dest="command", metavar="<command>")

    acc = sub.add_parser(
        "account",
        help="list accounts; reset a password, 2FA, lockout",
        usage=ACCOUNT_USAGE.removeprefix("usage:\n  "),
        add_help=False,
    )
    acc.add_argument("words", nargs=argparse.REMAINDER)

    st = sub.add_parser("setup", help="first-launch setup")
    st_sub = st.add_subparsers(dest="setup_command", metavar="<action>", required=True)
    st_sub.add_parser("token", help="show the one-time token for creating the super account")

    db = sub.add_parser("db", help="database migrations and backups")
    db_sub = db.add_subparsers(dest="db_command", metavar="<action>", required=True)
    db_sub.add_parser("migrate", help="apply pending database migrations")
    b = db_sub.add_parser(
        "backup", help="consistent copy of the SQLite database (safe while running)"
    )
    b.add_argument("path", nargs="?", help="where to write it (default: <state_dir>/backups/)")

    t = sub.add_parser(
        "test", help="run the end-to-end tester (see WIKI/tools/tester.md)", add_help=False
    )
    t.add_argument("args", nargs=argparse.REMAINDER)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    if args.command == "test":
        from toolchain.tester.__main__ import main as tester_main

        return tester_main(args.args)
    try:
        settings = load_settings()
        if args.command == "account":
            words = args.words
            if not words or words[0] in ("-h", "--help"):
                print(ACCOUNT_USAGE)
                return 0 if words else 2
            if words == ["list"]:
                account_list(settings)
            elif len(words) >= 2:
                account_action(settings, words[0], words[1:])
            else:
                raise UsageError(ACCOUNT_USAGE)
        elif args.command == "setup":
            setup_token(settings)
        elif args.command == "db":
            if args.db_command == "migrate":
                db_migrate(settings)
            else:
                db_backup(settings, args.path)
        return 0
    except UsageError as e:
        print(e, file=sys.stderr)
        return 2
    except CliError as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was changed.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
