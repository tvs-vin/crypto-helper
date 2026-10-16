"""7b CLI side: the agent's unit, `agent enable|disable`, and choosing services at install."""

import os

import pytest

from app.cli import CliError, main, service_choices
from app.cli import system as cli_system
from app.cli.layout import Layout, render_agent_unit
from app.cli.service import _apply_choices, write_units
from tests.test_embed_cli import config, installed  # noqa: F401 (fixture)


def test_agent_unit_is_root_but_boxed_in():
    unit = render_agent_unit(Layout())
    for line in (
        "User=root",
        "Group=crypto-helper",  # its socket belongs to the service user's group
        "ExecStart=/opt/crypto-helper/venv/bin/crypto-helper agent run",
        "RuntimeDirectory=crypto-helper-agent",
        "RuntimeDirectoryMode=0750",
        "PrivateNetwork=yes",
        "RestrictAddressFamilies=AF_UNIX",
        "NoNewPrivileges=yes",
        "ProtectHome=yes",
        "MemoryDenyWriteExecute=yes",
    ):
        assert line in unit, line
    caps = [ln for ln in unit.splitlines() if ln.startswith("CapabilityBoundingSet=")]
    assert caps == ["CapabilityBoundingSet="]  # no capabilities at all


def test_units_include_the_agent(tmp_path):
    layout = Layout(root=tmp_path, user="root")
    write_units(layout)
    assert layout.agent_unit.read_text() == render_agent_unit(layout)


@pytest.mark.parametrize(
    "value, chosen",
    [("agent,backups", {"agent", "backups"}), (" Embed ", {"embed"}), ("none", set())],
)
def test_parse_services(value, chosen):
    assert service_choices.parse(value) == chosen


def test_unknown_service_refused():
    with pytest.raises(CliError, match="terminal"):
        service_choices.parse("backups,terminal")


def test_choose_without_a_terminal_keeps_defaults_or_current(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    current = {"backups": True, "agent": False, "embed": True}
    assert service_choices.choose(None, current, new_install=True) == {"backups", "embed"}
    assert service_choices.choose(None, current, new_install=False) == {"backups", "embed"}
    assert service_choices.choose("agent", current, new_install=False) == {"agent"}


def test_choose_asks_on_a_new_install(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["", "n", "y"])  # backups: default yes, agent: no, embed: yes
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    defaults = {n: d for n, (d, _) in service_choices.OPTIONAL_SERVICES.items()}
    assert service_choices.choose(None, defaults, new_install=True) == {"backups", "embed"}


def test_apply_choices(installed, monkeypatch):  # noqa: F811
    started = []
    monkeypatch.setattr("app.cli.embed.start", lambda layout, updates, s: started.append(updates))
    layout = Layout(root=installed.config.parents[2], user="root")
    _apply_choices(layout, {"agent", "embed"})
    assert ("enable", "--quiet", "crypto-helper-agent.service") in installed.calls
    assert ("disable", "--now", "--quiet", "crypto-helper-backup.timer") in installed.calls
    assert started == [{"BOT_EMBED_ENABLED": "true"}]


def test_agent_enable_and_disable(installed, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setattr("app.cli.agent.ping", lambda timeout=5: {"services": {}})
    assert main(["agent", "enable"]) == 0
    assert ("enable", "--now", "--quiet", "crypto-helper-agent.service") in installed.calls
    assert "Agent on" in capsys.readouterr().out
    assert main(["agent", "disable"]) == 0
    assert ("disable", "--now", "--quiet", "crypto-helper-agent.service") in installed.calls


def test_agent_enable_reports_a_silent_agent(installed, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setattr("app.cli.agent.ping", lambda timeout=5: None)
    monkeypatch.setattr("app.cli.agent.time.sleep", lambda s: None)
    monkeypatch.setattr(cli_system, "journal_tail", lambda unit: "agent log here")
    assert main(["agent", "enable"]) == 1
    captured = capsys.readouterr()
    assert "didn't answer" in captured.err and "agent log here" in captured.out


def test_agent_needs_an_install(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CRYPTO_HELPER_ROOT", str(tmp_path))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert main(["agent", "status"]) == 1
    assert "isn't installed" in capsys.readouterr().err
