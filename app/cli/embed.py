"""`crypto-helper embed enable|disable|status`: the embed-only server."""

import re

from app.cli import system
from app.cli.common import PROG, CliError, bad, dim, load_settings, ok, require_root, step, warn
from app.cli.layout import current_layout
from app.cli.service import EMBED
from app.embeds.options import base_url
from app.netaccess import parse_hosts

KEY_RE = re.compile(r"^(BOT_[A-Z_]+)=")


def set_config(path, updates: dict[str, str]) -> None:
    """Change BOT_* lines in the config file in place. Writing in place (not a new file)
    keeps its owner and mode (root:crypto-helper, 640); comments stay too."""
    lines = path.read_text().splitlines()
    done = set()
    for i, line in enumerate(lines):
        m = KEY_RE.match(line)
        if m and m.group(1) in updates:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"
            done.add(m.group(1))
    missing = [k for k in updates if k not in done]
    if missing:
        lines += ["", "# Embeds (crypto-helper embed …)"] + [f"{k}={updates[k]}" for k in missing]
    path.write_text("\n".join(lines) + "\n")


def listening(s) -> str:
    where = ", ".join(parse_hosts(s.embed_hosts_value))
    same = " (same addresses as the web UI)" if s.embed_follows_main else ""
    return f"port {s.embed_port} on {where}{same}"


def check_embed_settings(s) -> None:
    """Refuse settings the embed server would refuse, with the same messages."""
    from app.cli.serve import check_embed_hosts

    check_embed_hosts(s)
    if not 1 <= s.embed_port <= 65535:
        raise CliError(f"Port {s.embed_port} isn't a valid port (1-65535).")
    if s.embed_port == s.port:
        raise CliError(f"Port {s.embed_port} is the main server's port; pick another one.")
    url = s.embed_public_url
    if url and not re.fullmatch(r"https?://[A-Za-z0-9.\-\[\]:]+(/[^\s]*)?", url):
        raise CliError(f"--public-url should look like https://embed.example.com, not {url!r}.")


def embed(
    action: str, host: str | None, port: int | None, public_url: str | None, allow_public: bool
) -> int:
    require_root(f"`embed {action}`")
    layout = current_layout()
    if not layout.is_installed():
        raise CliError(f"The service isn't installed. Run: sudo {PROG} service install")
    if action == "status":
        s = load_settings()
        state = system.unit_properties(EMBED, "ActiveState").get("ActiveState", "?")
        print(f"Embeds: {ok('on') if s.embed_enabled else dim('off')}; service {state}")
        print(f"  Listening: {listening(s)}" + (warn("  (public)") if s.embed_allow_public else ""))
        print(f"  Links use: {base_url(s)}")
        return 0
    if action == "disable":
        stop(layout)
        print(ok("Embeds are off.") + " Existing links stop working until you turn them back on.")
        return 0
    updates = {"BOT_EMBED_ENABLED": "true"}
    if host:
        updates["BOT_EMBED_HOST"] = host
    if port:
        updates["BOT_EMBED_PORT"] = str(port)
    if public_url is not None:
        updates["BOT_EMBED_PUBLIC_URL"] = public_url
    if allow_public:
        updates["BOT_EMBED_ALLOW_PUBLIC"] = "true"
    # Check the result before writing anything: a refused address must not be left in the
    # config with embeds switched on.
    now = load_settings()
    s = now.model_copy(
        update={
            "embed_enabled": True,
            "embed_host": host or now.embed_host,
            "embed_port": port or now.embed_port,
            "embed_public_url": now.embed_public_url if public_url is None else public_url,
            "embed_allow_public": allow_public or now.embed_allow_public,
        }
    )
    step("Updating the config and starting the embed server")
    try:
        start(layout, updates, s)
    except CliError:
        print(system.journal_tail(EMBED))
        raise
    print(ok(f"Embeds are on: {listening(s)}."))
    if not s.embed_public_url:
        print(
            warn("Links will point at ")
            + base_url(s)
            + ". For Discord or a website, publish the port with a tunnel and set "
            f"its address: sudo {PROG} embed enable --public-url https://embed.example.com"
        )
    if s.embed_allow_public:
        print(
            bad("Listening beyond this machine:") + " anyone who can reach it can load embeds "
            "whose link they know."
        )
    return 0


def start(layout, updates: dict[str, str], s) -> None:
    """Turn embeds on with the settings `s` (the config after `updates`). Checks first, so a
    refused setting changes nothing. Shared by the CLI and the agent (Services window)."""
    check_embed_settings(s)
    set_config(layout.config, updates)
    system.systemctl("daemon-reload")
    system.systemctl("enable", "--now", "--quiet", EMBED)
    system.systemctl("restart", EMBED)
    if not system.port_open("127.0.0.1", s.embed_port) and not _wait(s.embed_port):
        raise CliError("The embed server didn't start (sudo crypto-helper service logs).")


def stop(layout) -> None:
    set_config(layout.config, {"BOT_EMBED_ENABLED": "false"})
    system.systemctl("disable", "--now", "--quiet", EMBED, check=False)


def _wait(port: int) -> bool:
    import time

    for _ in range(40):
        if system.port_open("127.0.0.1", port):
            return True
        time.sleep(0.25)
    return False
