"""Run Alembic migrations programmatically (startup, CLI and tests share this)."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

MIGRATIONS = Path(__file__).with_name("migrations")
BASELINE = "0001"


def alembic_config(connection=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade(engine: Engine, target: str = "head") -> tuple[str | None, str | None]:
    """Bring the database to `target`. Returns (revision before, revision after).

    A database created before migrations existed (milestones 1-2 used create_all) has the
    baseline tables but no alembic_version table: it is stamped as the baseline first.
    """
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        cfg = alembic_config(conn)
        if "users" in tables and "alembic_version" not in tables:
            command.stamp(cfg, BASELINE)
        before = MigrationContext.configure(conn).get_current_revision()
        command.upgrade(cfg, target)
        after = MigrationContext.configure(conn).get_current_revision()
    return before, after
