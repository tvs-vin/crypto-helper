from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from app import migrate
from app.db import Base, make_engine


def fresh_engine():
    return make_engine("sqlite://")


def test_migrations_build_exactly_the_models():
    """If this fails, a model changed without a migration: run alembic --autogenerate."""
    engine = fresh_engine()
    migrate.upgrade(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_fresh_database_reaches_head():
    engine = fresh_engine()
    before, after = migrate.upgrade(engine)
    assert before is None and after == migrate.head_revision()
    assert migrate.upgrade(engine) == (after, after)  # running again is a no-op


def test_pre_migration_database_is_stamped_and_upgraded_keeping_data():
    """Milestone 1-2 databases were made with create_all and have no alembic_version."""
    engine = fresh_engine()
    migrate.upgrade(engine, "0001")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(
            text(
                "INSERT INTO users (username, password_hash, permissions, is_super, is_active, "
                "totp_enabled, failed_logins, preferences, created_at) VALUES "
                "('super', 'h', '[]', 1, 1, 0, 0, '{}', '2026-10-14 00:00:00')"
            )
        )
    before, after = migrate.upgrade(engine)
    assert before == "0001" and after == migrate.head_revision()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT username FROM users")).scalar() == "super"
        assert "recovery_codes" in inspect(conn).get_table_names()


def test_downgrade_and_upgrade_again():
    from alembic import command

    engine = fresh_engine()
    migrate.upgrade(engine)
    with engine.begin() as conn:
        command.downgrade(migrate.alembic_config(conn), "0001")
        assert "recovery_codes" not in inspect(conn).get_table_names()
    assert migrate.upgrade(engine)[1] == migrate.head_revision()


def test_app_startup_runs_migrations(app, client):
    assert migrate.current_revision(app.state.engine) == migrate.head_revision()
