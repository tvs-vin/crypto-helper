"""The embed server's CLI side: `serve --embed`, `embed enable|disable|status`, its unit."""

import os
import stat
import types

import pytest

from app.cli import CliError, main
from app.cli import system as cli_system
from app.cli.embed import set_config
from app.cli.layout import HARDENING, Layout, render_config, render_embed_unit
from app.cli.serve import check_embed_bind


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A fake install (config + unit file) with systemctl recorded instead of run."""
    layout = Layout(root=tmp_path, user="root")
    layout.etc.mkdir(parents=True)
    layout.config.write_text(render_config(layout))
    os.chmod(layout.config, 0o640)
    layout.unit.parent.mkdir(parents=True)
    layout.unit.write_text("[Unit]\n")
    monkeypatch.setenv("CRYPTO_HELPER_ROOT", str(tmp_path))
    monkeypatch.delenv("CRYPTO_HELPER_CONFIG", raising=False)
    for k in list(os.environ):
        if k.startswith("BOT_EMBED_"):
            monkeypatch.delenv(k)
    calls = []
    monkeypatch.setattr(cli_system, "systemctl", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(cli_system, "port_open", lambda host, port: True)
    monkeypatch.setattr(cli_system, "unit_properties", lambda *a: {"ActiveState": "active"})
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    return types.SimpleNamespace(config=layout.config, calls=calls)


def config(layout) -> dict:
    out = {}
    for line in layout.config.read_text().splitlines():
        if line.startswith("BOT_") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


# ---- config editing ----------------------------------------------------------------------


def test_set_config_replaces_appends_and_keeps_mode(tmp_path):
    p = tmp_path / "config.env"
    p.write_text("# comment stays\nBOT_HOST=127.0.0.1\nBOT_EMBED_ENABLED=false\n")
    os.chmod(p, 0o640)
    set_config(p, {"BOT_EMBED_ENABLED": "true", "BOT_EMBED_PORT": "8100"})
    text = p.read_text()
    assert "# comment stays" in text and "BOT_HOST=127.0.0.1" in text
    assert "BOT_EMBED_ENABLED=true" in text and "BOT_EMBED_ENABLED=false" not in text
    assert text.count("BOT_EMBED_PORT=8100") == 1
    assert stat.S_IMODE(p.stat().st_mode) == 0o640


# ---- bind rules ----------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_embed_loopback_is_fine(host):
    assert check_embed_bind(host, False) is None


@pytest.mark.parametrize("host", ["100.64.39.116", "192.168.1.5", "0.0.0.0"])
def test_embed_beyond_this_machine_needs_opt_in(host):
    with pytest.raises(CliError, match="BOT_EMBED_ALLOW_PUBLIC"):
        check_embed_bind(host, False)
    assert "anyone who can reach it" in check_embed_bind(host, True)


def test_serve_embed_refuses_while_embeds_are_off(installed, capsys):
    assert main(["serve", "--embed"]) == 1
    assert "Embeds are off" in capsys.readouterr().err


# ---- the unit ------------------------------------------------------------------------------


def test_embed_unit_runs_the_embed_server_in_the_same_sandbox():
    unit = render_embed_unit(Layout())
    assert "ExecStart=/opt/crypto-helper/venv/bin/crypto-helper serve --embed" in unit
    assert "User=crypto-helper" in unit and HARDENING in unit
    assert "EnvironmentFile=/etc/crypto-helper/config.env" in unit


# ---- enable / disable ----------------------------------------------------------------------


def test_enable_writes_config_and_starts_the_unit(installed, capsys):
    assert main(["embed", "enable", "--port", "8100"]) == 0
    c = config(installed)
    assert c["BOT_EMBED_ENABLED"] == "true" and c["BOT_EMBED_PORT"] == "8100"
    assert ("enable", "--now", "--quiet", "crypto-helper-embed.service") in installed.calls
    out = capsys.readouterr().out
    assert "Embeds are on" in out and "http://127.0.0.1:8100" in out


def test_enable_refuses_a_public_address_without_writing_anything(installed, capsys):
    before = installed.config.read_text()
    assert main(["embed", "enable", "--host", "192.168.1.5"]) == 1
    assert "BOT_EMBED_ALLOW_PUBLIC" in capsys.readouterr().err
    assert installed.config.read_text() == before and installed.calls == []


@pytest.mark.parametrize(
    "args, message",
    [
        (["--port", "8000"], "main server's port"),
        (["--public-url", "embed.example.com"], "should look like"),
    ],
)
def test_enable_refuses_bad_values_before_writing(installed, capsys, args, message):
    before = installed.config.read_text()
    assert main(["embed", "enable", *args]) == 1
    assert message in capsys.readouterr().err
    assert installed.config.read_text() == before


def test_public_address_with_opt_in_and_public_url(installed, capsys):
    assert (
        main(
            [
                "embed",
                "enable",
                "--host",
                "100.64.39.116",
                "--allow-public",
                "--public-url",
                "https://embed.example.com/",
            ]
        )
        == 0
    )
    c = config(installed)
    assert c["BOT_EMBED_HOST"] == "100.64.39.116" and c["BOT_EMBED_ALLOW_PUBLIC"] == "true"
    assert "Listening beyond this machine" in capsys.readouterr().out
    assert main(["embed", "status"]) == 0
    assert "https://embed.example.com" in capsys.readouterr().out


def test_disable(installed, capsys):
    main(["embed", "enable"])
    assert main(["embed", "disable"]) == 0
    assert config(installed)["BOT_EMBED_ENABLED"] == "false"
    assert ("disable", "--now", "--quiet", "crypto-helper-embed.service") in installed.calls


def test_embed_needs_an_install(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CRYPTO_HELPER_ROOT", str(tmp_path))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert main(["embed", "status"]) == 1
    assert "isn't installed" in capsys.readouterr().err


# ---- following the web UI's addresses ("main", the default) ------------------------------


def _settings(**kw):
    from app.config import Settings

    return Settings(_env_file=None, **kw)


def test_embed_follows_the_web_ui_by_default():
    from app.cli.serve import check_embed_hosts
    from app.embeds.options import base_url

    s = _settings(host="127.0.0.1,100.64.39.116", allow_remote_bind=True)
    assert s.embed_follows_main and s.embed_hosts_value == "127.0.0.1,100.64.39.116"
    # Already approved for the web UI, so no BOT_EMBED_ALLOW_PUBLIC needed; it still warns.
    warnings = check_embed_hosts(s)
    assert len(warnings) == 1 and "100.64.39.116" in warnings[0]
    # Links use the address other devices can reach, not 127.0.0.1.
    assert base_url(s) == "http://100.64.39.116:8001"
    assert base_url(_settings()) == "http://127.0.0.1:8001"
    assert (
        base_url(_settings(host="::1,fd00::5", allow_remote_bind=True)) == "http://[fd00::5]:8001"
    )


def test_following_the_web_ui_keeps_its_rules():
    from app.cli.serve import check_embed_hosts

    # A non-loopback BOT_HOST without BOT_ALLOW_REMOTE_BIND: the web UI would refuse it too.
    with pytest.raises(CliError, match="BOT_ALLOW_REMOTE_BIND"):
        check_embed_hosts(_settings(host="100.64.39.116"))
    with pytest.raises(CliError, match="every network interface"):
        check_embed_hosts(_settings(host="0.0.0.0", allow_remote_bind=True))


def test_own_addresses_still_need_allow_public():
    from app.cli.serve import check_embed_hosts

    s = _settings(host="127.0.0.1,100.64.39.116", allow_remote_bind=True, embed_host="10.0.0.5")
    assert not s.embed_follows_main
    with pytest.raises(CliError, match="BOT_EMBED_ALLOW_PUBLIC"):
        check_embed_hosts(s)


def test_status_says_it_follows_the_web_ui(installed, capsys):
    from app.cli.embed import set_config

    set_config(
        installed.config,
        {"BOT_HOST": "127.0.0.1,100.64.39.116", "BOT_ALLOW_REMOTE_BIND": "true"},
    )
    assert main(["embed", "enable"]) == 0
    assert "100.64.39.116" in capsys.readouterr().out
    assert main(["embed", "status"]) == 0
    out = capsys.readouterr().out
    assert "same addresses as the web UI" in out and "http://100.64.39.116:8001" in out


@pytest.mark.parametrize("args", [["serve"], ["serve", "--embed"]])
def test_serve_runs_the_app_with_the_settings_it_checked(tmp_path, monkeypatch, args):
    """The config file is read once; the app must not re-read different settings from the
    environment (it used to, which only went unnoticed because systemd sets both)."""
    import uvicorn

    cfg = tmp_path / "config.env"
    cfg.write_text(
        f"BOT_DATABASE_URL=sqlite:///{tmp_path}/bot.db\nBOT_EMBED_ENABLED=true\n"
        "BOT_PORT=18000\nBOT_EMBED_PORT=18001\nBOT_PRICE_BACKGROUND=false\n"
    )
    monkeypatch.setenv("CRYPTO_HELPER_CONFIG", str(cfg))
    monkeypatch.setattr("app.cli.serve.bind_socket", lambda host, port: None)
    seen = {}
    monkeypatch.setattr(
        uvicorn.Server, "run", lambda self, sockets: seen.update(app=self.config.app)
    )
    assert main(args) == 0
    settings = seen["app"].state.settings
    assert settings.database_url == f"sqlite:///{tmp_path}/bot.db" and settings.embed_port == 18001
