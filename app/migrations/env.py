"""Alembic environment. Used by `crypto-helper db migrate`, app startup and the tests."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401  (registers the tables on Base.metadata)
from app.db import Base

config = context.config
target_metadata = Base.metadata


def run_with(connection) -> None:
    # render_as_batch: SQLite can't ALTER most things, so Alembic rebuilds tables instead.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    run_with(connection)
else:  # plain `alembic` CLI during development: build an engine from the app settings
    from app.config import Settings

    config.set_main_option("sqlalchemy.url", Settings().database_url)
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as conn:
        run_with(conn)
