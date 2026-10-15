"""Commands that need root ask for sudo instead of failing."""

import os

import pytest

from app import cli
from app.cli import elevate as el


class Exec(Exception):
    """Raised instead of really replacing the process."""


@pytest.fixture
def execv(monkeypatch):
    calls = []

    def fake(path, args):
        calls.append((path, args))
        raise Exec

    monkeypatch.setattr(os, "execv", fake)
    monkeypatch.setattr(
        el.shutil, "which", lambda name: "/usr/bin/sudo" if name == "sudo" else None
    )
    monkeypatch.setattr(el.sys, "argv", ["/usr/local/bin/crypto-helper"])
    return calls


def as_user(monkeypatch, uid=1000):
    monkeypatch.setattr(os, "geteuid", lambda: uid)


def install(tmp_path, monkeypatch):
    """A fake installed layout under CRYPTO_HELPER_ROOT (set by conftest to tmp)."""
    root = tmp_path / "fake-root"
    monkeypatch.setenv("CRYPTO_HELPER_ROOT", str(root))
    for p in ("etc/crypto-helper/config.env", "etc/systemd/system/crypto-helper.service"):
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_text("")


@pytest.mark.parametrize(
    "argv",
    [
        ["service", "restart"],
        ["service", "status"],
        ["service", "logs", "-f"],
        ["service", "install", "--port", "8001"],
        ["service", "uninstall", "--purge", "--yes"],
        ["update", "--check"],
    ],
)
def test_system_commands_always_ask_for_sudo(monkeypatch, execv, argv):
    as_user(monkeypatch)
    with pytest.raises(Exec):
        cli.main(argv)
    path, args = execv[0]
    assert path == "/usr/bin/sudo"
    assert args[:4] == ["/usr/bin/sudo", "--", "env", "CRYPTO_HELPER_ELEVATED=1"]
    assert args[-len(argv) - 1 :] == ["/usr/local/bin/crypto-helper", *argv]  # same arguments


@pytest.mark.parametrize(
    "argv",
    [
        ["account", "list"],
        ["setup", "token"],
        ["db", "migrate"],
        ["prices", "check"],
        ["config", "show"],
        ["doctor"],
    ],
)
def test_data_commands_ask_only_when_the_service_is_installed(monkeypatch, execv, tmp_path, argv):
    as_user(monkeypatch)
    assert not el.needs_root(argv[0])  # running from a checkout: your own files, no sudo
    install(tmp_path, monkeypatch)
    assert el.needs_root(argv[0])
    with pytest.raises(Exec):
        cli.main(argv)
    assert execv[0][1][-len(argv) :] == argv


@pytest.mark.parametrize("command", ["serve", "test", "version"])
def test_never_elevated(monkeypatch, tmp_path, command):
    """serve runs as the service user under systemd and must never become root."""
    as_user(monkeypatch)
    install(tmp_path, monkeypatch)
    assert not el.needs_root(command)


def test_root_and_the_service_user_are_not_asked(monkeypatch, tmp_path):
    install(tmp_path, monkeypatch)
    as_user(monkeypatch, 0)
    assert not el.needs_root("service") and not el.needs_root("account")
    as_user(monkeypatch)
    monkeypatch.setattr(el, "_is_service_user", lambda: True)
    assert not el.needs_root("db")  # the backup timer runs `db backup` as the service user
    assert el.needs_root("service")  # but managing the service still needs root


def test_settings_survive_sudo(monkeypatch, execv, tmp_path):
    as_user(monkeypatch)
    monkeypatch.setenv("CRYPTO_HELPER_CONFIG", "/srv/custom.env")
    with pytest.raises(Exec):
        cli.main(["service", "status"])
    args = execv[0][1]
    assert "CRYPTO_HELPER_CONFIG=/srv/custom.env" in args
    assert any(a.startswith("CRYPTO_HELPER_ROOT=") for a in args)


def test_no_endless_loop_if_sudo_doesnt_make_us_root(monkeypatch, execv, capsys):
    as_user(monkeypatch)
    monkeypatch.setenv("CRYPTO_HELPER_ELEVATED", "1")
    assert cli.main(["service", "status"]) == 1
    assert "Still not running as root" in capsys.readouterr().err
    assert execv == []


def test_without_sudo_it_explains(monkeypatch, capsys):
    as_user(monkeypatch)
    monkeypatch.setattr(el.shutil, "which", lambda name: None)
    assert cli.main(["update"]) == 1
    assert "sudo isn't installed" in capsys.readouterr().err


def test_python_dash_m_reruns_the_same_way(monkeypatch, execv):
    as_user(monkeypatch)
    monkeypatch.setattr(el.sys, "argv", ["/repo/app/cli/__main__.py"])
    with pytest.raises(Exec):
        cli.main(["service", "status"])
    args = execv[0][1]
    assert args[-4:] == [el.sys.executable, "-m", "app.cli", "service"][-4:] or args[-5:-1] == [
        el.sys.executable,
        "-m",
        "app.cli",
        "service",
    ]


def test_says_why_before_sudo_prompts(monkeypatch, execv, capsys):
    as_user(monkeypatch)
    with pytest.raises(Exec):
        cli.main(["service", "restart"])
    assert "service needs administrator rights; asking sudo" in capsys.readouterr().err
