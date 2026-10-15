"""Unit tests for the service tooling. The real thing (systemd, useradd, rollback) is
exercised end to end on a VM by toolchain/servicetest; see WIKI/tools/service-test.md."""

import os
import stat
import time
from pathlib import Path

import pytest

from app.cli import CliError, main
from app.cli import common as cli_common
from app.cli.database import PRE_UPDATE_GLOB, prune_backups
from app.cli.layout import (
    HARDENING,
    Layout,
    current_layout,
    render_backup_timer,
    render_backup_unit,
    render_config,
    render_service_unit,
)
from app.cli.serve import check_bind, is_loopback
from app.cli.service import write_layout_files


@pytest.fixture
def layout(tmp_path):
    # The tests run as root, so "root" stands in for the service user (it always exists).
    return Layout(root=tmp_path, user="root")


def mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


# ---- layout and generated files ----------------------------------------------------------


def test_layout_paths_follow_root(layout, tmp_path):
    assert layout.config == tmp_path / "etc/crypto-helper/config.env"
    assert layout.db == tmp_path / "var/lib/crypto-helper/bot.db"
    assert layout.executable == tmp_path / "opt/crypto-helper/venv/bin/crypto-helper"
    assert not layout.is_installed()


def test_current_layout_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CRYPTO_HELPER_ROOT", str(tmp_path))
    assert current_layout().root == tmp_path


def test_service_unit_is_sandboxed_and_runs_as_service_user():
    unit = render_service_unit(Layout())
    assert (
        "User=crypto-helper" in unit
        and "ExecStart=/opt/crypto-helper/venv/bin/crypto-helper serve" in unit
    )
    for line in (
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "MemoryDenyWriteExecute=yes",
        "CapabilityBoundingSet=",
        "UMask=0077",
        "SystemCallFilter=@system-service",
        "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
    ):
        assert line in unit
    assert "Restart=on-failure" in unit and "WantedBy=multi-user.target" in unit


def test_backup_job_shares_the_sandbox_and_prunes():
    unit = render_backup_unit(Layout())
    assert HARDENING in unit
    assert "db backup --prune 14" in unit and "Type=oneshot" in unit
    timer = render_backup_timer(Layout())
    assert "OnCalendar=daily" in timer and "Persistent=true" in timer


def test_default_config_binds_locally_and_holds_no_secret():
    cfg = render_config(Layout())
    assert "BOT_HOST=127.0.0.1" in cfg
    assert "BOT_SECRET_KEY=" not in cfg  # only the key *file* path
    assert "BOT_SECRET_KEY_FILE=/etc/crypto-helper/secret.key" in cfg


# ---- installing files --------------------------------------------------------------------


def test_write_layout_files_creates_private_files(layout):
    created = write_layout_files(layout)
    assert any("secret.key" in c for c in created)
    assert mode(layout.etc) == 0o750
    assert mode(layout.state) == 0o700 and mode(layout.backups) == 0o700
    assert mode(layout.config) == 0o640 and mode(layout.key) == 0o640
    assert mode(layout.unit) == 0o644
    from cryptography.fernet import Fernet

    Fernet(layout.key.read_bytes().strip())  # a valid key
    assert layout.is_installed()


def test_reinstall_never_overwrites_config_or_key(layout):
    write_layout_files(layout)
    layout.config.write_text("BOT_PORT=9999\n")
    key = layout.key.read_text()
    os.chmod(layout.key, 0o644)  # someone loosened it
    created = write_layout_files(layout)
    assert created == []
    assert layout.config.read_text() == "BOT_PORT=9999\n"
    assert layout.key.read_text() == key
    assert mode(layout.key) == 0o640  # tightened again


def test_root_only_commands_explain_if_sudo_didnt_give_root(monkeypatch, capsys):
    """After elevation, each command still checks it really is root (belt and braces)."""
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr("app.cli.elevate.needs_root", lambda command: False)
    monkeypatch.setattr("app.cli.needs_root", lambda command: False)
    assert main(["service", "install"]) == 1
    assert main(["update", "--check"]) == 1
    assert "needs root" in capsys.readouterr().err


# ---- serve: bind address -----------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "127.0.0.53"])
def test_loopback_hosts(host):
    assert is_loopback(host)
    assert check_bind(host, allow_remote=False) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", ""])
def test_all_interfaces_always_refused(host):
    with pytest.raises(CliError, match="every network interface"):
        check_bind(host, allow_remote=True)


def test_private_address_needs_explicit_opt_in():
    with pytest.raises(CliError, match="BOT_ALLOW_REMOTE_BIND"):
        check_bind("100.64.39.116", allow_remote=False)
    assert "Anyone who can reach" in check_bind("100.64.39.116", allow_remote=True)


# ---- backups -----------------------------------------------------------------------------


def test_prune_keeps_newest_and_only_matching(tmp_path):
    for i in range(5):
        f = tmp_path / f"bot-2026010{i}.db"
        f.write_text("x")
        os.utime(f, (time.time() + i, time.time() + i))
    (tmp_path / "pre-update-abc.db").write_text("x")
    (tmp_path / "my-own-copy.db").write_text("x")
    removed = prune_backups(tmp_path, 2)
    assert sorted(p.name for p in removed) == [
        "bot-20260100.db",
        "bot-20260101.db",
        "bot-20260102.db",
    ]
    assert {p.name for p in tmp_path.iterdir()} == {
        "bot-20260103.db",
        "bot-20260104.db",
        "pre-update-abc.db",
        "my-own-copy.db",
    }
    assert prune_backups(tmp_path, 1, PRE_UPDATE_GLOB) == []


def test_prune_flag_rules(tmp_path, monkeypatch, capsys):
    db = tmp_path / "bot.db"
    import sqlite3

    sqlite3.connect(db).close()
    cfg = tmp_path / "c.env"
    cfg.write_text(f"BOT_DATABASE_URL=sqlite:///{db}\nBOT_STATE_DIR={tmp_path}\n")
    monkeypatch.setenv("CRYPTO_HELPER_CONFIG", str(cfg))
    backups = Path(os.environ["BOT_STATE_DIR"]) / "backups"
    assert main(["db", "backup", str(tmp_path / "x.db"), "--prune", "3"]) == 1
    assert main(["db", "backup", "--prune", "0"]) == 1
    assert not (tmp_path / "x.db").exists() and not backups.exists()  # refused up front
    for _ in range(3):  # same second: names get a -2, -3 suffix instead of failing
        assert main(["db", "backup", "--prune", "2"]) == 0
    assert len(list(backups.glob("bot-*.db"))) == 2


# ---- CLI plumbing ------------------------------------------------------------------------


def test_cli_creates_private_files(tmp_path, monkeypatch):
    """The CLI sets umask 077: anything it creates without an explicit mode is private."""
    db = tmp_path / "fresh.db"
    cfg = tmp_path / "c.env"
    cfg.write_text(f"BOT_DATABASE_URL=sqlite:///{db}\n")
    monkeypatch.setenv("CRYPTO_HELPER_CONFIG", str(cfg))
    old = os.umask(0o022)
    try:
        assert main(["db", "migrate"]) == 0
    finally:
        os.umask(old)
    assert mode(db) == 0o600


def test_missing_tool_is_a_clear_error():
    with pytest.raises(CliError, match="isn't installed"):
        cli_common.run(["definitely-not-a-real-command-xyz"])


def test_sbin_tools_are_found_even_without_sbin_on_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert cli_common.which("useradd") in ("/usr/sbin/useradd", "/sbin/useradd")


def test_no_privilege_drop_when_not_installed():
    assert cli_common.drop_to_service_user() is False


def test_version_and_config_show(capsys, tmp_path, monkeypatch):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.startswith("crypto-helper ")
    cfg = tmp_path / "c.env"
    cfg.write_text("BOT_SECRET_KEY=super-secret-value-123\n")
    monkeypatch.setenv("CRYPTO_HELPER_CONFIG", str(cfg))
    monkeypatch.delenv("BOT_SECRET_KEY")
    assert main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert "super-secret-value-123" not in out and "<set, hidden>" in out


def test_doctor_runs_outside_an_install(capsys):
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    assert "Not installed as a service" in out and "ok," in out
