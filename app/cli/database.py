"""`crypto-helper setup token` and `crypto-helper db ...`"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app import migrate
from app.cli.common import CliError, load_settings, open_db
from app.config import Settings
from app.db import make_engine
from app.models import User
from app.setup_token import read_setup_token

BACKUP_GLOB = "bot-*.db"
PRE_UPDATE_GLOB = "pre-update-*.db"


def setup_token() -> None:
    settings = load_settings()
    engine, factory = open_db(settings, require_current=False)
    if migrate.current_revision(engine) is not None:  # no tables yet = server never started
        with factory() as db:
            if db.scalar(select(User.id).limit(1)) is not None:
                raise CliError("Setup is already done: the super account exists.")
    token = read_setup_token(settings)
    if token is None:
        raise CliError("No setup token yet. Start the server: it creates one on first launch.")
    print(token)


def db_migrate() -> None:
    engine = make_engine(load_settings().database_url)
    before, after = migrate.upgrade(engine)
    if before == after:
        print(f"Database is up to date (revision {after}).")
    else:
        print(f"Database migrated: {before or 'empty'} -> {after}.")


def sqlite_path(settings: Settings) -> Path:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise CliError("Backups are only supported for SQLite databases.")
    return Path(url.removeprefix("sqlite:///"))


def backup_dir(settings: Settings) -> Path:
    return Path(settings.state_dir) / "backups"


def write_backup(source: Path, dest: Path) -> None:
    """SQLite online backup: a consistent snapshot even while the server is writing."""
    if not source.exists():
        raise CliError(f"Database file {source} doesn't exist.")
    if dest.exists():
        raise CliError(f"{dest} already exists. Choose another path.")
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The backup holds password hashes and encrypted secrets: private from the first byte.
    os.close(os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()


def prune_backups(folder: Path, keep: int, pattern: str = BACKUP_GLOB) -> list[Path]:
    """Delete the oldest backups matching `pattern`, keeping the newest `keep`."""
    files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = files[keep:]
    for f in removed:
        f.unlink()
    return removed


def db_backup(target: str | None, prune: int | None) -> Path:
    # Check every argument before writing anything.
    if prune is not None and target:
        raise CliError("--prune only applies to the default backup folder.")
    if prune is not None and prune < 1:
        raise CliError("--prune must keep at least 1 backup.")
    settings = load_settings()
    source = sqlite_path(settings)
    if target:
        dest = Path(target)
    else:
        stamp = f"bot-{datetime.now():%Y%m%d-%H%M%S}"
        dest = backup_dir(settings) / f"{stamp}.db"
        n = 2
        while dest.exists():  # two backups in the same second
            dest = backup_dir(settings) / f"{stamp}-{n}.db"
            n += 1
    write_backup(source, dest)
    print(f"Backup written to {dest}")
    if prune is not None:
        for f in prune_backups(dest.parent, prune):
            print(f"Removed old backup {f.name}")
    print(
        "Note: 2FA secrets in it can only be read with the same secret key, so back up "
        "the key file too (separately)."
    )
    return dest


def latest_backup(settings: Settings) -> Path | None:
    folder = backup_dir(settings)
    if not folder.exists():
        return None
    files = sorted(folder.glob(BACKUP_GLOB), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None
