import io
import sqlite3
import stat

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import accounts, cli, migrate
from app.db import make_engine, make_session_factory
from app.models import AuditLog, RecoveryCode, Session, User
from app.security import hash_password, verify_password
from app.timeutil import utcnow
from tests.conftest import PASSWORD, H

NEW_PW = "cli-chosen-passphrase"


def empty_config(tmp_path):
    """An empty config file, so the CLI never picks up a real installed one."""
    path = tmp_path / "empty.env"
    path.touch()
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A file database at head with `super` and `bob`; the CLI finds it via the env."""
    db_path = tmp_path / "bot.db"
    monkeypatch.setenv("BOT_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CRYPTO_HELPER_CONFIG", str(empty_config(tmp_path)))
    engine = make_engine(f"sqlite:///{db_path}")
    migrate.upgrade(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        db.add(
            User(
                username="super",
                password_hash=hash_password(PASSWORD),
                permissions=[],
                is_super=True,
            )
        )
        db.add(
            User(
                username="bob", password_hash=hash_password(PASSWORD), permissions=["wallets.view"]
            )
        )
        db.commit()
    return factory, db_path


def run(*argv, stdin=None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return cli.main(list(argv))


def get(factory, name) -> User:
    with factory() as db:
        return db.scalar(select(User).where(User.username == name))


def last_audit(factory) -> AuditLog:
    with factory() as db:
        return db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()


def add_session(factory, name):
    with factory() as db:
        user = db.scalar(select(User).where(User.username == name))
        db.add(
            Session(
                token_hash=f"{name}-hash-{utcnow().timestamp()}",
                user_id=user.id,
                expires_at=utcnow().replace(year=2099),
            )
        )
        db.commit()


def sessions_of(factory, name) -> int:
    with factory() as db:
        uid = db.scalar(select(User.id).where(User.username == name))
        return len(db.scalars(select(Session).where(Session.user_id == uid)).all())


# ---- usage --------------------------------------------------------------------------------


def test_no_command_prints_help(capsys):
    assert cli.main([]) == 2
    assert "account" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["account"],
        ["account", "bob"],
        ["account", "bob", "explode"],
        ["account", "bob", "password", "--force"],
        ["account", "bob", "unlock", "--stdin"],
    ],
)
def test_bad_account_usage(env, capsys, argv):
    assert cli.main(argv) == 2
    captured = capsys.readouterr()
    assert "account <name> password" in captured.out + captured.err


def test_password_is_never_accepted_as_an_argument(env, capsys):
    """`account bob password hunter2...` must not silently set it from argv."""
    assert cli.main(["account", "bob", "password", "some-new-passphrase"]) == 2
    assert verify_password(get(env[0], "bob").password_hash, PASSWORD)


# ---- account list -------------------------------------------------------------------------


def test_account_list(env, capsys):
    assert cli.main(["account", "list"]) == 0
    out = capsys.readouterr().out
    assert "super" in out and "ALL (super)" in out and "bob" in out and "wallets.view" in out
    assert "$argon2" not in out


# ---- account password ---------------------------------------------------------------------


def test_password_from_stdin_changes_it_unlocks_and_signs_out(env, monkeypatch, capsys):
    factory, _ = env
    add_session(factory, "super")
    with factory() as db:
        u = db.scalar(select(User).where(User.username == "super"))
        u.locked_until, u.failed_logins = utcnow().replace(year=2099), 3
        db.commit()
    assert (
        run("account", "super", "password", "--stdin", stdin=NEW_PW + "\n", monkeypatch=monkeypatch)
        == 0
    )
    u = get(factory, "super")
    assert verify_password(u.password_hash, NEW_PW)
    assert u.locked_until is None and u.failed_logins == 0
    assert sessions_of(factory, "super") == 0
    row = last_audit(factory)
    assert row.username == "<cli>" and row.source_ip == "local-cli"
    assert "super" in row.detail and NEW_PW not in row.detail
    assert NEW_PW not in capsys.readouterr().out


def test_password_prompt_requires_matching_entries(env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    answers = iter([NEW_PW, "something-else-entirely"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli.main(["account", "bob", "password"]) == 1
    assert "don't match" in capsys.readouterr().err
    assert verify_password(get(env[0], "bob").password_hash, PASSWORD)


def test_password_prompt_happy_path(env, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": NEW_PW)
    assert cli.main(["account", "bob", "password"]) == 0
    assert verify_password(get(env[0], "bob").password_hash, NEW_PW)


def test_password_length_enforced(env, monkeypatch, capsys):
    assert run("account", "bob", "password", "--stdin", stdin="short", monkeypatch=monkeypatch) == 1
    assert "12 to 256" in capsys.readouterr().err


def test_unknown_account(env, monkeypatch, capsys):
    assert (
        run("account", "ghost", "password", "--stdin", stdin=NEW_PW, monkeypatch=monkeypatch) == 1
    )
    assert "No account named 'ghost'" in capsys.readouterr().err


# ---- unlock / sessions / 2fa ---------------------------------------------------------------


def test_unlock(env):
    factory, _ = env
    with factory() as db:
        db.scalar(select(User).where(User.username == "bob")).locked_until = utcnow().replace(
            year=2099
        )
        db.commit()
    assert cli.main(["account", "bob", "unlock"]) == 0
    assert get(factory, "bob").locked_until is None


def test_sessions_revoke(env, capsys):
    factory, _ = env
    add_session(factory, "bob")
    add_session(factory, "bob")
    add_session(factory, "super")
    assert cli.main(["account", "bob", "sessions", "revoke"]) == 0
    assert sessions_of(factory, "bob") == 0 and sessions_of(factory, "super") == 1
    assert "2 session(s)" in capsys.readouterr().out


def test_2fa_reset_for_super(env, capsys):
    factory, _ = env
    with factory() as db:
        u = db.scalar(select(User).where(User.username == "super"))
        u.totp_enabled, u.totp_secret, u.totp_last_step = True, "encrypted", 5
        accounts.issue_recovery_codes(db, u)
        db.commit()
    add_session(factory, "super")
    assert cli.main(["account", "super", "2fa", "reset"]) == 0
    u = get(factory, "super")
    assert not u.totp_enabled and u.totp_secret is None and u.totp_last_step is None
    with factory() as db:
        assert db.scalar(select(RecoveryCode)) is None
    assert sessions_of(factory, "super") == 0
    assert last_audit(factory).action == "2fa.reset"


def test_2fa_reset_when_not_set_up(env, capsys):
    assert cli.main(["account", "bob", "2fa", "reset"]) == 1
    assert "doesn't have 2FA" in capsys.readouterr().err


def test_account_commands_refuse_an_outdated_database(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "old.db"
    monkeypatch.setenv("BOT_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CRYPTO_HELPER_CONFIG", str(empty_config(tmp_path)))
    migrate.upgrade(make_engine(f"sqlite:///{db_path}"), "0001")
    assert cli.main(["account", "list"]) == 1
    assert "crypto-helper db migrate" in capsys.readouterr().err
    assert cli.main(["db", "migrate"]) == 0
    assert "0001 -> " in capsys.readouterr().out
    assert cli.main(["account", "list"]) == 0
    assert cli.main(["db", "migrate"]) == 0
    assert "up to date" in capsys.readouterr().out


# ---- setup token ---------------------------------------------------------------------------


def test_setup_token_shown_then_gone(tmp_path, monkeypatch, capsys):
    from app.config import Settings
    from app.main import create_app

    db_path = tmp_path / "bot.db"
    monkeypatch.setenv("BOT_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CRYPTO_HELPER_CONFIG", str(empty_config(tmp_path)))
    assert cli.main(["setup", "token"]) == 1
    assert "Start the server" in capsys.readouterr().err
    app = create_app(Settings())
    with TestClient(app) as c:
        capsys.readouterr()  # drop the server's first-launch banner
        assert cli.main(["setup", "token"]) == 0
        assert capsys.readouterr().out.strip() == app.state.setup_token
        c.post("/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H)
    assert cli.main(["setup", "token"]) == 1
    assert "already done" in capsys.readouterr().err


# ---- db backup -----------------------------------------------------------------------------


def test_backup_is_a_private_consistent_copy(env, tmp_path, capsys):
    _, db_path = env
    dest = tmp_path / "copy.db"
    assert cli.main(["db", "backup", str(dest)]) == 0
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    con = sqlite3.connect(dest)
    assert {r[0] for r in con.execute("SELECT username FROM users")} == {"super", "bob"}
    con.close()
    assert cli.main(["db", "backup", str(dest)]) == 1  # never overwrites


def test_backup_default_location(env, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BOT_STATE_DIR", str(tmp_path / "state"))
    assert cli.main(["db", "backup"]) == 0
    files = list((tmp_path / "state" / "backups").glob("bot-*.db"))
    assert len(files) == 1


def test_test_command_passes_options_through(monkeypatch):
    """Regression: `crypto-helper test --target live` used to fail in argparse."""
    seen = {}

    def fake_tester(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("toolchain.tester.__main__.main", fake_tester)
    assert cli.main(["test", "--target", "live", "--suite", "auth"]) == 0
    assert seen["argv"] == ["--target", "live", "--suite", "auth"]


# ---- account rules (12a) ------------------------------------------------------------------


def test_account_rules_on_and_off(env, capsys):
    factory, _ = env
    assert cli.main(["account", "bob", "new-password", "on"]) == 0
    assert "must choose a new password" in capsys.readouterr().out
    assert cli.main(["account", "bob", "require-2fa", "on"]) == 0
    with factory() as db:
        bob = db.scalar(select(User).where(User.username == "bob"))
        assert (bob.must_change_password, bob.require_2fa) == (True, True)
        actions = db.scalars(select(AuditLog.detail).where(AuditLog.action == "user.update")).all()
        assert actions == ["bob (id 2): must_change_password=True", "bob (id 2): require_2fa=True"]
    assert cli.main(["account", "bob", "new-password", "off"]) == 0
    with factory() as db:
        assert db.scalar(select(User).where(User.username == "bob")).must_change_password is False
    assert cli.main(["account", "super", "require-2fa", "off"]) == 1
    assert "super's rules are fixed" in capsys.readouterr().err
    assert cli.main(["account", "bob", "require-2fa", "maybe"]) == 2
