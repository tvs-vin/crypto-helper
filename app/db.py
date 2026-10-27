from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url == "sqlite://":
            kwargs["poolclass"] = StaticPool
        else:
            path = url.removeprefix("sqlite:///")
            if path:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        # Python's sqlite3 driver only starts a transaction at the first write, so reads
        # before it aren't protected. Take over: SQLAlchemy's documented recipe for real
        # SQLite transactions, plus an opt-in BEGIN IMMEDIATE (see begin_immediate).

        @event.listens_for(engine, "connect")
        def _connect(dbapi_conn, _record):
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cur.close()

        @event.listens_for(engine, "begin")
        def _begin(conn):
            immediate = conn.get_execution_options().get(IMMEDIATE)
            conn.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine


IMMEDIATE = "sqlite_begin_immediate"
# How long a write waits for another to finish before "database is locked" (read at connect).
BUSY_TIMEOUT_MS = 5000


def begin_immediate(db: Session) -> None:
    """Start a transaction that holds SQLite's write lock from its first statement.

    Use it before read-then-write logic on money (check a balance, then change it): a
    second request trying the same waits until this one commits, so both can't pass the
    check against the same old balance. Any open read transaction is committed first.
    """
    db.commit()
    db.connection(execution_options={IMMEDIATE: True})


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    if request.method in WRITE_METHODS:
        # A request that may write takes SQLite's write lock up front. Two writers that both
        # read first (the session check) would otherwise deadlock on upgrading their read
        # locks, and SQLite fails one at once with "database is locked". This way the second
        # one simply waits its turn (busy_timeout). Reads (GET) are unaffected.
        session.connection(execution_options={IMMEDIATE: True})
    try:
        yield session
    finally:
        session.close()
