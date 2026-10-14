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
    render_backup_timer,
    render_backup_unit,
    render_config,
    render_service_unit,
)

SERVICE = f"{NAME}.service"
TIMER = f"{NAME}-backup.timer"


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
    for path, text in (
        (layout.unit, render_service_unit(layout)),
        (layout.backup_unit, render_backup_unit(layout)),
        (layout.backup_timer, render_backup_timer(layout)),
    ):
        system.write_file(path, text, 0o644)
    return created


def install(port: int | None) -> int:
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

    step("Starting the service and the daily backup timer")
    system.systemctl("daemon-reload")
    system.systemctl("enable", "--quiet", SERVICE, TIMER)
    system.systemctl("restart", SERVICE)
    system.systemctl("start", TIMER)

    settings = load_settings()
    health = system.wait_healthy(settings.host, settings.port)
    if health is None:
        print(system.journal_tail(SERVICE))
        raise CliError(
            f"The service didn't come up. See the log above, or: sudo {PROG} service logs"
        )
    print()
    print(ok(f"Crypto Helper is running on http://{settings.host}:{settings.port}"))
    print(f"  Config:   {layout.config}")
    print(f"  Data:     {layout.state}")
    print(f"  Key:      {layout.key}  <- back this up somewhere safe, off this machine")
    print(f"  Command:  {PROG} --help")
    if health.get("setup_required"):
        print()
        print("Next: create the super account. Get the one-time token with")
        print(f"  sudo {PROG} setup token")
        print("then follow WIKI/guides/getting-started.md (step 3).")
    print(f"\nCheck everything with: sudo {PROG} doctor")
    return 0


# ---- uninstall ---------------------------------------------------------------------------


def uninstall(purge: bool, yes: bool) -> int:
    require_root("Uninstalling the service")
    layout = current_layout()
    question = (
        f"Remove the {NAME} service?"
        if not purge
        else f"Remove the {NAME} service AND delete all its data, config and code?"
    )
    if not confirm(question, yes):
        print("Cancelled. Nothing was changed.")
        return 1

    if system.have("systemctl"):
        step("Stopping and removing the systemd units")
        system.systemctl("disable", "--now", "--quiet", SERVICE, TIMER, check=False)
    for unit in (layout.unit, layout.backup_unit, layout.backup_timer):
        unit.unlink(missing_ok=True)
    if system.have("systemctl"):
        system.systemctl("daemon-reload", check=False)

    if not purge:
        print(ok("Service removed."))
        print("Kept (reinstall any time with `sudo crypto-helper service install`):")
        for p in (layout.config, layout.key, layout.state, layout.opt, layout.bin_link):
            print(f"  {p}")
        print(f"To delete everything: sudo {PROG} service uninstall --purge")
        return 0

    # Safety net: keep one last copy of the database and key, readable only by root.
    saved = None
    if layout.db.exists() or layout.key.exists():
        saved = layout.root / "root" / f"{NAME}-purged-{datetime.now():%Y%m%d-%H%M%S}"
        saved.mkdir(parents=True, mode=0o700)
        for f in (layout.db, layout.key, layout.config):
            if f.exists():
                shutil.copy2(f, saved / f.name)
    step("Deleting data, config, code and the service user")
    for path in (layout.state, layout.etc, layout.opt):
        shutil.rmtree(path, ignore_errors=True)
    layout.bin_link.unlink(missing_ok=True)
    run(["userdel", layout.user], check=False)
    print(ok("Crypto Helper is completely removed."))
    if saved:
        print(
            f"A final copy of the database, key and config is in {saved} (root only). "
            "Delete it when you're sure you don't need it."
        )
    return 0


# ---- start / stop / restart / status / logs ----------------------------------------------


def control(action: str) -> int:
    require_root(f"`service {action}`")
    layout = current_layout()
    _require_installed(layout)
    system.systemctl(action, SERVICE)
    if action == "stop":
        print("Stopped.")
        return 0
    settings = load_settings()
    if system.wait_healthy(settings.host, settings.port) is None:
        print(system.journal_tail(SERVICE))
        raise CliError(f"The service didn't come up after `{action}`. See the log above.")
    print(ok(f"Running on http://{settings.host}:{settings.port}"))
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
    url = f"http://{settings.host}:{settings.port}"
    health = system.wait_healthy(settings.host, settings.port, timeout=2) if active else None
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
