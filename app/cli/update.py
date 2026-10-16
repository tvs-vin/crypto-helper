"""`crypto-helper update`: pull, back up, migrate, restart, health-check, roll back on failure."""

import shutil
from datetime import datetime

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
from app.cli.database import PRE_UPDATE_GLOB, prune_backups
from app.cli.deploy import CODE_UMASK, install_commit, preflight
from app.cli.layout import NAME, current_layout
from app.cli.service import AGENT, EMBED, SERVICE, write_units
from app.netaccess import probe_host

KEEP_PRE_UPDATE = 5


def _git(src, *args, check=True) -> str:
    return run(["git", "-C", str(src), *args], check=check, umask=CODE_UMASK).stdout.strip()


def update(check_only: bool, yes: bool) -> int:
    require_root("Updating")
    layout = current_layout()
    if not layout.is_installed() or not (layout.src / ".git").exists():
        raise CliError("No installed copy to update. Install first: sudo ./install.sh")
    src = layout.src
    branch = _git(src, "rev-parse", "--abbrev-ref", "HEAD")

    step(f"Checking for updates on {branch}")
    _git(src, "fetch", "--quiet", "origin", branch)
    old = _git(src, "rev-parse", "HEAD")
    new = _git(src, "rev-parse", f"origin/{branch}")
    if old == new:
        print(ok(f"Already up to date ({old[:7]})."))
        return 0
    ancestor = run(["git", "-C", str(src), "merge-base", "--is-ancestor", old, new], check=False)
    if ancestor.returncode != 0:
        raise CliError(
            f"origin/{branch} isn't a fast-forward of the installed version {old[:7]} "
            "(history was rewritten). Refusing to update automatically."
        )
    print(_git(src, "log", "--oneline", "--no-decorate", f"{old}..{new}"))
    if check_only:
        print(f"\nRun `sudo {PROG} update` to install these.")
        return 0
    if _git(src, "status", "--porcelain"):
        raise CliError(f"{src} has local changes. Refusing to overwrite them.")
    if not confirm(f"Install {new[:7]} (currently {old[:7]})?", yes):
        print("Cancelled. Nothing was changed.")
        return 1

    settings = load_settings()
    backup = layout.backups / f"pre-update-{old[:7]}-{datetime.now():%Y%m%d-%H%M%S}.db"
    step(f"Backing up the database to {backup}")
    if layout.db.exists():
        run([str(layout.executable), "db", "backup", str(backup)], user=layout.user)
    else:
        backup = None

    step("Stopping the service")
    system.systemctl("stop", SERVICE)
    system.systemctl("stop", EMBED, check=False)  # it must not read the DB mid-migration
    try:
        step(f"Installing {new[:7]}")
        _git(src, "merge", "--ff-only", "--quiet", new)
        install_commit(layout, new)
        preflight(layout)
        # New versions can add or change units (e.g. the embed server): refresh them.
        write_units(layout)
        system.systemctl("daemon-reload")
        step("Applying database migrations")
        print(
            dim(
                "    "
                + run([str(layout.executable), "db", "migrate"], user=layout.user).stdout.strip()
            )
        )
        step("Starting the service")
        system.systemctl("start", SERVICE)
        if settings.embed_enabled:
            system.systemctl("start", EMBED, check=False)
        system.systemctl("try-restart", AGENT, check=False)  # new code, if it's running
        if system.wait_healthy(probe_host(settings.host), settings.port, timeout=30) is None:
            raise CliError("the new version didn't answer within 30 seconds")
    except CliError as failure:
        _rollback(layout, src, old, backup, settings)
        raise CliError(
            f"Update to {new[:7]} failed ({failure}). Rolled back to {old[:7]}; your data is "
            f"as it was. Recent log lines are above. Nothing else to do: try again later or "
            f"check `sudo {PROG} service logs`."
        ) from None

    print(ok(f"Updated {old[:7]} -> {new[:7]}. Running and healthy."))
    if backup:
        print(f"The pre-update backup stays in {backup}.")
        for f in prune_backups(layout.backups, KEEP_PRE_UPDATE, PRE_UPDATE_GLOB):
            print(dim(f"Removed old pre-update backup {f.name}"))
    return 0


def _rollback(layout, src, old: str, backup, settings) -> None:
    print(bad("\nUpdate failed. Rolling back..."))
    print(system.journal_tail(SERVICE, 30))
    system.systemctl("stop", SERVICE, check=False)
    _git(src, "reset", "--hard", "--quiet", old, check=False)
    try:
        install_commit(layout, old)
    except CliError as e:
        print(bad(f"Reinstalling {old[:7]} failed: {e}"))
    if backup and backup.exists():
        # The new code may have migrated the schema forward: put the old file back whole.
        for suffix in ("", "-journal", "-wal", "-shm"):
            (layout.db.parent / (layout.db.name + suffix)).unlink(missing_ok=True)
        shutil.copy2(backup, layout.db)
        system.chown(layout.db, layout.user, layout.user)
    system.systemctl("start", SERVICE, check=False)
    if system.wait_healthy(probe_host(settings.host), settings.port, timeout=30) is None:
        print(
            bad(
                f"The old version didn't come back up either. Check `sudo {PROG} service "
                f"logs` and `sudo {PROG} doctor`. Database backup: {backup}"
            )
        )
    else:
        print(warn(f"Rolled back to {old[:7]} and running again."))


__all__ = ["update", "NAME"]
