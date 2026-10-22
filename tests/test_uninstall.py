"""12e: uninstalling, verified without touching the real system. Everything is "installed" into
a throwaway root; systemctl and userdel must never run (a test root has neither), and after a
purge nothing may be left but the deliberate final copy."""

import stat
import types
from pathlib import Path

import pytest

from app.cli import service, system
from app.cli.layout import NAME, Layout
from app.cli.service import uninstall_plan, write_layout_files


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A full install under tmp_path: config, key, units, data, backups, code, the command's
    link, and a `systemctl edit` drop-in. ("root" stands in for the service user.)"""
    root = tmp_path / "root-fs"
    layout = Layout(root=root, user="root")
    write_layout_files(layout)
    layout.db.write_bytes(b"SQLite format 3\0 pretend")
    (layout.backups / "pre-update-abc.db").write_bytes(b"old")
    (layout.src / ".git").mkdir(parents=True)
    layout.executable.parent.mkdir(parents=True)
    layout.executable.write_text("#!/bin/sh\n")
    layout.bin_link.parent.mkdir(parents=True)
    layout.bin_link.symlink_to(layout.executable)
    dropin = layout.unit.with_name(layout.unit.name + ".d")
    dropin.mkdir()
    (dropin / "override.conf").write_text("[Service]\n")
    stamp = root / "var/lib/systemd/timers" / f"stamp-{NAME}-backup.timer"  # systemd's
    stamp.parent.mkdir(parents=True)
    stamp.write_text("")
    monkeypatch.setenv("CRYPTO_HELPER_ROOT", str(root))
    monkeypatch.setattr(service, "require_root", lambda what: None)

    def never(*a, **k):  # a throwaway root must never reach the real systemd or accounts
        raise AssertionError(f"ran for real: {a}")

    monkeypatch.setattr(system, "systemctl", never)
    monkeypatch.setattr(service, "run", never)
    return types.SimpleNamespace(root=root, layout=layout, dropin=dropin)


def tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def test_purge_leaves_nothing_but_the_final_copy(installed, capsys):
    assert service.uninstall(purge=True, yes=True) == 0
    left = [p for p in installed.root.rglob("*") if p.is_file() or p.is_symlink()]
    copies = list((installed.root / "root").glob(f"{NAME}-purged-*"))
    assert len(copies) == 1
    assert sorted(p.name for p in left) == ["bot.db", "config.env", "secret.key"]
    assert all(p.parent == copies[0] for p in left)
    assert stat.S_IMODE(copies[0].stat().st_mode) == 0o700  # root only
    assert (copies[0] / "bot.db").read_bytes() == b"SQLite format 3\0 pretend"
    # Not a single folder of ours left either (empty system folders like etc/systemd stay).
    ours = [p for p in tree(installed.root) if NAME in p and f"{NAME}-purged-" not in p]
    assert ours == []
    out = capsys.readouterr().out
    assert "completely removed" in out and "Left on purpose" in out


def test_plain_uninstall_removes_only_the_units(installed, capsys):
    layout = installed.layout
    assert service.uninstall(purge=False, yes=True) == 0
    assert not layout.unit.exists() and not layout.agent_unit.exists()
    assert not installed.dropin.exists()
    for kept in (layout.config, layout.key, layout.db, layout.executable, layout.bin_link):
        assert kept.exists(), kept
    assert "Kept" in capsys.readouterr().out


def test_dry_run_lists_exactly_and_changes_nothing(installed, capsys):
    before = tree(installed.root)
    assert service.uninstall(purge=True, yes=False, dry_run=True) == 0
    assert tree(installed.root) == before
    out = capsys.readouterr().out
    layout = installed.layout
    for path in (layout.unit, layout.state, layout.etc, layout.opt, layout.bin_link,
                 installed.dropin):  # fmt: skip
        assert str(path) in out, path
    assert "the database, key and config" in out and "nothing was changed" in out
    assert "the folder you ran install.sh from" in out  # what stays, said plainly


def test_dry_run_and_real_run_share_one_plan(installed):
    steps, _ = uninstall_plan(installed.layout, purge=True)
    kinds = [what for what, _ in steps]
    assert "stop and disable" not in kinds and "delete account" not in kinds  # test root
    service.uninstall(purge=True, yes=True)
    for what, target in steps:
        if what.startswith("delete"):
            assert not Path(target).exists() and not Path(target).is_symlink(), target


def test_a_link_that_isnt_ours_is_left_alone(installed, tmp_path):
    other = tmp_path / "someone-elses-program"
    other.write_text("#!/bin/sh\n")
    installed.layout.bin_link.unlink()
    installed.layout.bin_link.symlink_to(other)
    service.uninstall(purge=True, yes=True)
    assert installed.layout.bin_link.is_symlink() and other.exists()


def test_only_the_account_install_made_is_ever_deleted(monkeypatch):
    def entry(uid, gecos):
        return lambda name: types.SimpleNamespace(pw_uid=uid, pw_gecos=gecos)

    import pwd

    monkeypatch.setattr(pwd, "getpwnam", entry(988, system.USER_COMMENT))
    assert service._ours_user(NAME)
    monkeypatch.setattr(pwd, "getpwnam", entry(1000, "Vin"))
    assert not service._ours_user("vin")  # a person
    monkeypatch.setattr(pwd, "getpwnam", entry(0, system.USER_COMMENT))
    assert not service._ours_user("root")  # never root, whatever its comment


def test_cancelled_changes_nothing(installed, monkeypatch, capsys):
    before = tree(installed.root)
    monkeypatch.setattr(service, "confirm", lambda question, yes: False)
    assert service.uninstall(purge=True, yes=False) == 1
    assert tree(installed.root) == before


def test_the_cli_passes_dry_run(installed, capsys, monkeypatch):
    import app.cli as cli

    monkeypatch.setattr(cli, "needs_root", lambda command: False)  # no sudo re-run
    assert cli.main(["service", "uninstall", "--purge", "--dry-run"]) == 0
    assert "Uninstalling would" in capsys.readouterr().out
    assert installed.layout.config.exists()
