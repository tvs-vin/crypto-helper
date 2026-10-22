"""`crypto-helper service ...`: install and run as a systemd service, NetBird-style."""

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

from app.cli import system
from app.cli.common import (
    PROG,
    CliError,
    bad,
    confirm,
    dim,
    load_settings,
    ok,
    require_root,
    run,
    step,
    warn,
)
from app.cli.layout import (
    NAME,
    Layout,
    current_layout,
    render_agent_unit,
    render_backup_timer,
    render_backup_unit,
    render_config,
    render_embed_unit,
    render_service_unit,
)
from app.netaccess import probe_host, urls

SERVICE = f"{NAME}.service"
EMBED = f"{NAME}-embed.service"
TIMER = f"{NAME}-backup.timer"
AGENT = f"{NAME}-agent.service"


def _require_installed(layout: Layout) -> None:
    if not layout.is_installed():
        raise CliError(f"The service isn't installed. Run: sudo {PROG} service install")


# ---- install -----------------------------------------------------------------------------


def write_layout_files(layout: Layout) -> list[str]:
    """Create the user, folders, config, key and unit files. Never overwrites config or key.

    Returns a list of what was created, for the summary.
    """
    created = []
    u = layout.user
    if system.ensure_system_user(u, layout.state):
        created.append(f"system user {u}")
    # Config: root owns it (the service can't rewrite its own settings), group can read.
    system.ensure_dir(layout.etc, 0o750, "root", u)
    system.ensure_dir(layout.state, 0o700, u, u)
    system.ensure_dir(layout.backups, 0o700, u, u)
    if not layout.config.exists():
        system.write_file(layout.config, render_config(layout), 0o640, "root", u, exclusive=True)
        created.append(str(layout.config))
    if not layout.key.exists():
        key = Fernet.generate_key().decode()
        system.write_file(layout.key, key + "\n", 0o640, "root", u, exclusive=True)
        created.append(f"{layout.key} (new encryption key: back it up!)")
    else:
        os.chmod(layout.key, 0o640)
        system.chown(layout.key, "root", u)
    write_units(layout)
    return created


def write_units(layout: Layout) -> None:
    """(Re)write the managed systemd unit files. Never touches config or key."""
    for path, text in (
        (layout.unit, render_service_unit(layout)),
        (layout.embed_unit, render_embed_unit(layout)),
        (layout.agent_unit, render_agent_unit(layout)),
        (layout.backup_unit, render_backup_unit(layout)),
        (layout.backup_timer, render_backup_timer(layout)),
    ):
        system.write_file(path, text, 0o644)


def _is_enabled(unit: str) -> bool:
    return system.unit_properties(unit, "UnitFileState").get("UnitFileState") == "enabled"


def install(port: int | None, services: str | None = None) -> int:
    require_root("Installing the service")
    system.require_systemd()
    layout = current_layout()
    if port:
        layout = Layout(root=layout.root, user=layout.user, port=port)
    if not layout.executable.exists():
        raise CliError(
            f"{layout.executable} doesn't exist. Install with ./install.sh from a checkout, "
            "which sets up the code and then runs this command."
        )
    running = system.unit_properties(SERVICE, "ActiveState").get("ActiveState") == "active"
    if not running and system.port_open("127.0.0.1", layout.port):
        raise CliError(
            f"Something is already listening on port {layout.port}. Stop it, or install on "
            f"another port: sudo {PROG} service install --port 8001"
        )

    from app.cli import service_choices

    new_install = not layout.config.exists()
    if new_install:
        current = {n: default for n, (default, _) in service_choices.OPTIONAL_SERVICES.items()}
    else:
        current = {
            "backups": _is_enabled(TIMER),
            "agent": _is_enabled(AGENT),
            "embed": load_settings().embed_enabled,
        }
    chosen = service_choices.choose(services, current, new_install)

    step("Creating user, folders, config and encryption key")
    created = write_layout_files(layout)
    for item in created:
        print(f"    created {item}")

    step("Applying database migrations")
    print(
        dim(
            "    " + run([str(layout.executable), "db", "migrate"], user=layout.user).stdout.strip()
        )
    )

    step("Starting the service")
    system.systemctl("daemon-reload")
    system.systemctl("enable", "--quiet", SERVICE)
    system.systemctl("restart", SERVICE)
    _apply_choices(layout, chosen)

    settings = load_settings()
    health = system.wait_healthy(probe_host(settings.host), settings.port)
    if health is None:
        print(system.journal_tail(SERVICE))
        raise CliError(
            f"The service didn't come up. See the log above, or: sudo {PROG} service logs"
        )
    print()
    print(ok(f"Crypto Helper is running on {', '.join(urls(settings.host, settings.port))}"))
    print(f"  Config:   {layout.config}")
    print(f"  Data:     {layout.state}")
    print(f"  Key:      {layout.key}  <- back this up somewhere safe, off this machine")
    print(f"  Command:  {PROG} --help")
    if health.get("setup_required"):
        print()
        print("Next: create the super account. Get the one-time token with")
        print(f"  sudo {PROG} setup token")
        print("then follow WIKI/guides/getting-started.md (step 3).")
    print(
        "  Services: " + (", ".join(sorted(chosen)) or "none") + dim("  (change: Services window)")
    )
    print(f"\nCheck everything with: sudo {PROG} doctor")
    return 0


def _apply_choices(layout: Layout, chosen: set[str]) -> None:
    from app.cli import embed

    for name in ("backups", "agent"):
        unit = TIMER if name == "backups" else AGENT
        if name in chosen:
            step(f"Turning on {name}")
            system.systemctl("enable", "--quiet", unit)
            system.systemctl("restart", unit)
        else:
            system.systemctl("disable", "--now", "--quiet", unit, check=False)
    settings = load_settings()
    if "embed" in chosen:
        step("Turning on the embed server")
        embed.start(
            layout,
            {"BOT_EMBED_ENABLED": "true"},
            settings.model_copy(update={"embed_enabled": True}),
        )
    elif settings.embed_enabled:
        embed.stop(layout)


# ---- uninstall ---------------------------------------------------------------------------


def _ours_user(name: str) -> bool:
    """Only the account install made (its comment says so), and never root or a person."""
    import pwd

    try:
        pw = pwd.getpwnam(name)
    except KeyError:
        return False
    return pw.pw_uid != 0 and pw.pw_gecos == system.USER_COMMENT


def _ours_link(layout: Layout) -> bool:
    """/usr/local/bin/crypto-helper, if it's our link into the install's venv (not some other
    program's file)."""
    p = layout.bin_link
    return p.is_symlink() and Path(os.readlink(p)).resolve().is_relative_to(layout.opt.resolve())


def uninstall_plan(layout: Layout, purge: bool) -> tuple[list[tuple[str, Path | str]], list[str]]:
    """What uninstalling removes, step by step, and what stays. The real run and --dry-run
    both use this list, so the dry run is exactly what would happen."""
    real = layout.root == Path("/")  # a test root has no systemd and no accounts of its own
    steps: list[tuple[str, Path | str]] = []
    if real and system.have("systemctl"):
        steps.append(("stop and disable", ", ".join((SERVICE, EMBED, TIMER, AGENT))))
    for unit in (layout.unit, layout.embed_unit, layout.agent_unit, layout.backup_unit,
                 layout.backup_timer):  # fmt: skip
        if unit.exists():
            steps.append(("delete file", unit))
        dropins = unit.with_name(unit.name + ".d")  # from `systemctl edit`
        if dropins.is_dir() and not dropins.is_symlink():
            steps.append(("delete folder", dropins))
    stamp = layout.root / "var/lib/systemd/timers" / f"stamp-{TIMER}"  # the timer's last run
    if stamp.is_file() and not stamp.is_symlink():
        steps.append(("delete file", stamp))
    stays = []
    if not purge:
        stays = [
            f"{layout.config} and {layout.key} (config and encryption key)",
            f"{layout.state} (database and backups)",
            f"{layout.opt} (code)",
            f"{layout.bin_link} (the command)",
            f"the {layout.user} account",
        ]
        return steps, stays
    if layout.db.exists() or layout.key.exists():
        steps.append(("save a final copy (root only) of", "the database, key and config"))
    for path in (layout.state, layout.etc, layout.opt):
        if path.exists() and not path.is_symlink():
            steps.append(("delete folder", path))
    if _ours_link(layout):
        steps.append(("delete link", layout.bin_link))
    elif layout.bin_link.exists() or layout.bin_link.is_symlink():
        stays.append(f"{layout.bin_link}: it isn't the install's link, so it's left alone")
    if real and _ours_user(layout.user):
        steps.append(("delete account", layout.user))
    stays += [
        f"the final copy in {layout.root / 'root'}/{NAME}-purged-<time>/ (delete it when sure)",
        "the folder you ran install.sh from (your own git clone)",
        f"old log lines in the system journal (journalctl -u {SERVICE}; they age out)",
        "packages install.sh needed (git, python3-venv): shared with other programs",
        "~/.config/crypto-helper/ of anyone who ran it from a checkout (a development key,"
        " not made by the installer)",
    ]
    return steps, stays


def uninstall(purge: bool, yes: bool, dry_run: bool = False) -> int:
    require_root("Uninstalling the service")
    layout = current_layout()
    steps, stays = uninstall_plan(layout, purge)
    if dry_run:
        print("Uninstalling would:" if steps else "Nothing to remove.")
        for what, target in steps:
            print(f"  - {what} {target}")
        print("It keeps:")
        for item in stays:
            print(f"  - {item}")
        print(dim("(dry run: nothing was changed)"))
        return 0
    question = (
        f"Remove the {NAME} service?"
        if not purge
        else f"Remove the {NAME} service AND delete all its data, config and code?"
    )
    if not confirm(question, yes):
        print("Cancelled. Nothing was changed.")
        return 1

    saved = None
    for what, target in steps:
        if what == "stop and disable":
            step("Stopping and removing the systemd units")
            system.systemctl("disable", "--now", "--quiet", SERVICE, EMBED, TIMER, AGENT,
                             check=False)  # fmt: skip
        elif what == "delete file":
            Path(target).unlink(missing_ok=True)
        elif what == "save a final copy (root only) of":
            # Safety net: one last copy of the database, key and config, readable only by root.
            saved = layout.root / "root" / f"{NAME}-purged-{datetime.now():%Y%m%d-%H%M%S}"
            saved.mkdir(parents=True, mode=0o700)
            for f in (layout.db, layout.key, layout.config):
                if f.exists():
                    shutil.copy2(f, saved / f.name)
        elif what == "delete folder":
            if Path(target) in (layout.state, layout.etc, layout.opt):
                step(f"Deleting {target}")
            shutil.rmtree(target, ignore_errors=True)
        elif what == "delete link":
            Path(target).unlink(missing_ok=True)
        elif what == "delete account":
            run(["userdel", str(target)], check=False)
    if layout.root == Path("/") and system.have("systemctl"):
        system.systemctl("daemon-reload", check=False)

    if not purge:
        print(ok("Service removed."))
        print("Kept (reinstall any time with `sudo crypto-helper service install`):")
        for item in stays:
            print(f"  {item}")
        print(f"To delete everything: sudo {PROG} service uninstall --purge")
        return 0
    print(ok("Crypto Helper is completely removed."))
    if saved:
        print(
            f"A final copy of the database, key and config is in {saved} (root only). "
            "Delete it when you're sure you don't need it."
        )
    print("Left on purpose: " + "; ".join(stays[1:]) + ".")
    return 0


# ---- start / stop / restart / status / logs ----------------------------------------------


def control(action: str) -> int:
    require_root(f"`service {action}`")
    layout = current_layout()
    _require_installed(layout)
    settings = load_settings()
    system.systemctl(action, SERVICE)
    if action == "stop" or settings.embed_enabled:  # the embed server follows the main one
        system.systemctl(action, EMBED, check=False)
    if action == "stop":
        print("Stopped.")
        return 0
    if system.wait_healthy(probe_host(settings.host), settings.port) is None:
        print(system.journal_tail(SERVICE))
        raise CliError(f"The service didn't come up after `{action}`. See the log above.")
    print(ok(f"Running on {', '.join(urls(settings.host, settings.port))}"))
    return 0


def _since(timestamp: str) -> str:
    return timestamp if timestamp and timestamp != "n/a" else "unknown"


def status() -> int:
    from app.cli.info import version_string

    layout = current_layout()
    print(f"{NAME} {version_string()}")
    if not layout.is_installed():
        print(warn("Not installed as a service.") + " Install: sudo ./install.sh")
        return 3
    p = system.unit_properties(
        SERVICE,
        "ActiveState",
        "SubState",
        "UnitFileState",
        "MainPID",
        "ActiveEnterTimestamp",
        "NRestarts",
    )
    active = p.get("ActiveState") == "active"
    state = f"{p.get('ActiveState')} ({p.get('SubState')})"
    print(
        f"  Service:  {ok(state) if active else bad(state)}"
        + (
            f" since {_since(p.get('ActiveEnterTimestamp', ''))}, pid {p.get('MainPID')}"
            if active
            else ""
        )
    )
    print(
        f"  At boot:  {p.get('UnitFileState')}"
        + (f", restarted {p.get('NRestarts')} time(s)" if p.get("NRestarts", "0") != "0" else "")
    )
    try:
        settings = load_settings()
    except CliError as e:
        print(f"  Config:   {warn(str(e))}")
        return 0 if active else 3
    url = ", ".join(urls(settings.host, settings.port))
    health = (
        system.wait_healthy(probe_host(settings.host), settings.port, timeout=2) if active else None
    )
    print(f"  Web:      {url}  " + (ok("answering") if health else bad("not answering")))
    if health is not None:
        print(
            "  Setup:    "
            + (
                warn(f"waiting: sudo {PROG} setup token")
                if health.get("setup_required")
                else "done"
            )
        )
    t = system.unit_properties(TIMER, "ActiveState", "NextElapseUSecRealtime")
    from app.cli.database import latest_backup

    last = None
    try:
        last = latest_backup(settings)
    except PermissionError:
        pass
    last_s = (
        datetime.fromtimestamp(last.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        if last
        else "none yet"
    )
    print(
        f"  Backups:  last {last_s}; timer {t.get('ActiveState')}, next "
        f"{t.get('NextElapseUSecRealtime') or '?'}"
    )
    print(f"  Config:   {layout.config}")
    return 0 if active else 3


def logs(follow: bool, lines: int) -> int:
    if not system.have("journalctl"):
        raise CliError("journalctl isn't available on this machine.")
    cmd = [
        "journalctl",
        "-u",
        SERVICE,
        "-u",
        f"{NAME}-backup.service",
        "-u",
        EMBED,
        "-u",
        AGENT,
        "-n",
        str(lines),
        "-o",
        "short-iso",
    ]
    cmd.append("-f" if follow else "--no-pager")
    sys.stdout.flush()
    os.execv(system.which("journalctl"), cmd)
    return 0  # not reached


def bin_link_target(layout: Layout) -> Path | None:
    try:
        return layout.bin_link.resolve() if layout.bin_link.is_symlink() else None
    except OSError:
        return None
