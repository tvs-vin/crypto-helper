"""`crypto-helper`: install, run and administer the Crypto Helper server.

Commands are noun first, then the thing, then the verb, e.g.
    crypto-helper account super password
Account and database commands work directly on the database, so they run on the VM
itself. That access is the root of trust: it's the only way to change `super`.
"""

import argparse
import os
import sys

from app.cli.common import PROG, CliError, UsageError, drop_to_service_user
from app.cli.elevate import needs_root, rerun_with_sudo
from app.cli.service_choices import OPTIONAL_SERVICES

# Commands that touch the database. Run as root on an installed system, they switch to the
# service user first so every file they create belongs to the service.
DROPS_PRIVILEGES = {"account", "setup", "db"}


def build_parser() -> argparse.ArgumentParser:
    from app.cli.account import ACCOUNT_USAGE

    p = argparse.ArgumentParser(
        prog=PROG,
        description="Install, run and administer the Crypto Helper server.",
        epilog=f"Run `{PROG} <command> --help` for details. Docs: WIKI/reference/cli.md",
    )
    sub = p.add_subparsers(dest="command", metavar="<command>")

    acc = sub.add_parser(
        "account",
        help="list accounts; reset a password, 2FA or lockout",
        usage=ACCOUNT_USAGE.removeprefix("usage:\n  "),
        add_help=False,
    )
    acc.add_argument("words", nargs=argparse.REMAINDER)

    st = sub.add_parser("setup", help="first-launch setup")
    st_sub = st.add_subparsers(dest="action", metavar="<action>", required=True)
    st_sub.add_parser("token", help="show the one-time token for creating the super account")

    db = sub.add_parser("db", help="database migrations and backups")
    db_sub = db.add_subparsers(dest="action", metavar="<action>", required=True)
    db_sub.add_parser("migrate", help="apply pending database migrations")
    b = db_sub.add_parser("backup", help="consistent copy of the database (safe while running)")
    b.add_argument("path", nargs="?", help="where to write it (default: <state_dir>/backups/)")
    b.add_argument(
        "--prune",
        type=int,
        metavar="N",
        help="then keep only the newest N backups in the default folder",
    )

    svc = sub.add_parser("service", help="install and control the systemd service")
    svc_sub = svc.add_subparsers(dest="action", metavar="<action>", required=True)
    i = svc_sub.add_parser("install", help="create the service user, files and units; start it")
    i.add_argument("--port", type=int, help="port for a new install (default 8000)")
    i.add_argument(
        "--services",
        help="which optional services to run, comma-separated, from: "
        + ", ".join(OPTIONAL_SERVICES)
        + ' ("none" for none). Without it a new install asks; a reinstall keeps what\'s on.',
    )
    u = svc_sub.add_parser("uninstall", help="remove the service (keeps data unless --purge)")
    u.add_argument(
        "--purge",
        action="store_true",
        help="also delete data, config, key, code and the service user",
    )
    u.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    for name, text in (
        ("start", "start the service"),
        ("stop", "stop the service"),
        ("restart", "restart (e.g. after editing the config)"),
    ):
        svc_sub.add_parser(name, help=text)
    svc_sub.add_parser("status", help="is it running, answering, backed up?")
    lg = svc_sub.add_parser("logs", help="show the service log (journalctl)")
    lg.add_argument("-f", "--follow", action="store_true", help="keep printing new lines")
    lg.add_argument("-n", "--lines", type=int, default=100, help="how many lines (default 100)")

    up = sub.add_parser(
        "update", help="pull the latest version, migrate, restart; rolls back if it fails"
    )
    up.add_argument("--check", action="store_true", help="only show what would be installed")
    up.add_argument("--yes", action="store_true", help="don't ask for confirmation")

    pr = sub.add_parser("prices", help="check live prices from the price source")
    pr_sub = pr.add_subparsers(dest="action", metavar="<action>", required=True)
    chk = pr_sub.add_parser("check", help="fetch live prices now (bypasses the cache)")
    chk.add_argument("--fiat", default="usd", help="usd, eur, gbp, jpy, cad or aud")

    sub.add_parser("doctor", help="check the whole setup and suggest fixes")
    sv = sub.add_parser(
        "serve", help="run the web server in the foreground (the service uses this)"
    )
    sv.add_argument("--embed", action="store_true", help="run the embed-only server instead")
    em = sub.add_parser("embed", help="the embed-only server: turn it on or off")
    em_sub = em.add_subparsers(dest="action", metavar="<action>", required=True)
    en = em_sub.add_parser("enable", help="turn embeds on and start the embed server")
    en.add_argument(
        "--host",
        help='address(es) to listen on; "main" (the default) means the same as the web UI',
    )
    en.add_argument("--port", type=int, help="port (default 8001)")
    en.add_argument("--public-url", help="the address people reach embeds at (e.g. a tunnel)")
    en.add_argument(
        "--allow-public",
        action="store_true",
        help="allow listening beyond this machine (e.g. 0.0.0.0)",
    )
    em_sub.add_parser("disable", help="stop the embed server; links stop working")
    em_sub.add_parser("status", help="is it on, where, which address links use")
    ag = sub.add_parser("agent", help="the root helper behind the Services window")
    ag_sub = ag.add_subparsers(dest="action", metavar="<action>", required=True)
    ag_sub.add_parser("enable", help="start the agent (lets the Services window manage services)")
    ag_sub.add_parser("disable", help="stop the agent")
    ag_sub.add_parser("status", help="is it running, and what it sees")
    ag_sub.add_parser("run", help="the agent itself (systemd runs this)")
    tb = ag_sub.add_parser("terminal-bridge", help="one terminal session (the agent starts this)")
    tb.add_argument("--socket", required=True)
    tb.add_argument("--cols", type=int, default=100)
    tb.add_argument("--rows", type=int, default=30)
    tb.add_argument("--host")
    sub.add_parser("version", help="show the installed version")
    cfg = sub.add_parser("config", help="show the effective configuration")
    cfg_sub = cfg.add_subparsers(dest="action", metavar="<action>", required=True)
    cfg_sub.add_parser("show", help="print settings (secrets hidden)")

    t = sub.add_parser(
        "test", help="run the end-to-end tester (WIKI/tools/tester.md)", add_help=False
    )
    t.add_argument("args", nargs=argparse.REMAINDER)
    return p


def dispatch(args) -> int:
    cmd = args.command
    if cmd == "account":
        from app.cli.account import run_account

        return run_account(args.words)
    if cmd == "setup":
        from app.cli.database import setup_token

        setup_token()
        return 0
    if cmd == "db":
        from app.cli.database import db_backup, db_migrate

        if args.action == "migrate":
            db_migrate()
        else:
            db_backup(args.path, args.prune)
        return 0
    if cmd == "service":
        from app.cli import service

        if args.action == "install":
            return service.install(args.port, args.services)
        if args.action == "uninstall":
            return service.uninstall(args.purge, args.yes)
        if args.action == "status":
            return service.status()
        if args.action == "logs":
            return service.logs(args.follow, args.lines)
        return service.control(args.action)
    if cmd == "update":
        from app.cli.update import update

        return update(args.check, args.yes)
    if cmd == "prices":
        from app.cli.prices import prices_check

        return prices_check(args.fiat)
    if cmd == "doctor":
        from app.cli.doctor import doctor

        return doctor()
    if cmd == "serve":
        from app.cli.serve import serve, serve_embed

        return serve_embed() if args.embed else serve()
    if cmd == "embed":
        from app.cli.embed import embed

        return embed(
            args.action,
            getattr(args, "host", None),
            getattr(args, "port", None),
            getattr(args, "public_url", None),
            getattr(args, "allow_public", False),
        )
    if cmd == "agent":
        from app.cli.agent import agent

        if args.action == "terminal-bridge":
            from app.cli.agent import terminal_bridge

            return terminal_bridge(args.socket, args.cols, args.rows, args.host)
        return agent(args.action)
    if cmd == "version":
        from app.cli.info import show_version

        return show_version()
    if cmd == "config":
        from app.cli.info import show_config

        return show_config()
    raise UsageError(f"Unknown command {cmd!r}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "test":
        # Hand everything after `test` to the tester untouched (argparse would try to
        # interpret options like --target itself).
        from toolchain.tester.__main__ import main as tester_main

        return tester_main(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    # Everything this tool creates (databases, backups, keys) is private.
    os.umask(0o077)
    try:
        if needs_root(args.command):
            rerun_with_sudo(args.command, argv)
        explicit_backup_path = args.command == "db" and getattr(args, "path", None)
        if args.command in DROPS_PRIVILEGES and not explicit_backup_path:
            drop_to_service_user()
        return dispatch(args)
    except UsageError as e:
        print(e, file=sys.stderr)
        return 2
    except CliError as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
