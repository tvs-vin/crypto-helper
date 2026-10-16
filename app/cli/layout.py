"""Where an installed Crypto Helper lives on disk, and the files we generate for it.

Every path derives from `root` so the tests can "install" into a temp folder.
Set CRYPTO_HELPER_ROOT to do the same by hand.
"""

import os
from dataclasses import dataclass
from pathlib import Path

NAME = "crypto-helper"


@dataclass(frozen=True)
class Layout:
    root: Path = Path("/")
    user: str = NAME
    port: int = 8000

    # code
    @property
    def opt(self) -> Path:
        return self.root / "opt" / NAME

    @property
    def venv(self) -> Path:
        return self.opt / "venv"

    @property
    def src(self) -> Path:
        """A git clone of the repo; `crypto-helper update` pulls into it."""
        return self.opt / "src"

    @property
    def executable(self) -> Path:
        return self.venv / "bin" / NAME

    @property
    def bin_link(self) -> Path:
        return self.root / "usr" / "local" / "bin" / NAME

    # config (root-owned, readable by the service group)
    @property
    def etc(self) -> Path:
        return self.root / "etc" / NAME

    @property
    def config(self) -> Path:
        return self.etc / "config.env"

    @property
    def key(self) -> Path:
        return self.etc / "secret.key"

    # data (owned by the service user, private)
    @property
    def state(self) -> Path:
        return self.root / "var" / "lib" / NAME

    @property
    def db(self) -> Path:
        return self.state / "bot.db"

    @property
    def backups(self) -> Path:
        return self.state / "backups"

    # systemd
    @property
    def unit_dir(self) -> Path:
        return self.root / "etc" / "systemd" / "system"

    @property
    def unit(self) -> Path:
        return self.unit_dir / f"{NAME}.service"

    @property
    def backup_unit(self) -> Path:
        return self.unit_dir / f"{NAME}-backup.service"

    @property
    def backup_timer(self) -> Path:
        return self.unit_dir / f"{NAME}-backup.timer"

    @property
    def embed_unit(self) -> Path:
        return self.unit_dir / f"{NAME}-embed.service"

    def is_installed(self) -> bool:
        """Works for any user. The files inside /etc/crypto-helper are locked to root and the
        service, so a normal user can't even check whether config.env exists (Python raises
        PermissionError); the folder itself and the unit file are visible to everyone."""
        return self.etc.is_dir() and self.unit.exists()


def current_layout() -> Layout:
    return Layout(root=Path(os.environ.get("CRYPTO_HELPER_ROOT", "/")))


# ---- generated files ---------------------------------------------------------------------

MANAGED = (
    "# Managed by `crypto-helper service install`: changes here are overwritten.\n"
    "# For local tweaks use: sudo systemctl edit {unit}\n"
)

# Sandboxing shared by the server and the backup job. Each line removes something the app
# never needs; `systemd-analyze security crypto-helper` scores the result.
HARDENING = """\
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
ProtectProc=invisible
ProcSubset=pid
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RemoveIPC=yes
CapabilityBoundingSet=
AmbientCapabilities=
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources
SystemCallErrorNumber=EPERM
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
DevicePolicy=closed
UMask=0077
StateDirectory=crypto-helper
StateDirectoryMode=0700
"""


def render_service_unit(layout: Layout) -> str:
    return f"""{MANAGED.format(unit=layout.unit.name)}
[Unit]
Description=Crypto Helper (self-hosted crypto dashboard)
Documentation=file://{layout.src}/WIKI/index.md
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=exec
User={layout.user}
Group={layout.user}
Environment=CRYPTO_HELPER_CONFIG={layout.config}
EnvironmentFile={layout.config}
WorkingDirectory={layout.state}
ExecStart={layout.executable} serve
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
{HARDENING}
[Install]
WantedBy=multi-user.target
"""


def render_embed_unit(layout: Layout) -> str:
    return f"""{MANAGED.format(unit=layout.embed_unit.name)}
[Unit]
Description=Crypto Helper embeds (read-only embed pages and preview images)
Documentation=file://{layout.src}/WIKI/guides/embeds.md
After=network-online.target {NAME}.service
Wants=network-online.target

[Service]
Type=exec
User={layout.user}
Group={layout.user}
Environment=CRYPTO_HELPER_CONFIG={layout.config}
EnvironmentFile={layout.config}
WorkingDirectory={layout.state}
ExecStart={layout.executable} serve --embed
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
{HARDENING}
[Install]
WantedBy=multi-user.target
"""


def render_backup_unit(layout: Layout) -> str:
    return f"""{MANAGED.format(unit=layout.backup_unit.name)}
[Unit]
Description=Crypto Helper daily database backup
Documentation=file://{layout.src}/WIKI/guides/backups.md

[Service]
Type=oneshot
User={layout.user}
Group={layout.user}
Environment=CRYPTO_HELPER_CONFIG={layout.config}
EnvironmentFile={layout.config}
WorkingDirectory={layout.state}
ExecStart={layout.executable} db backup --prune 14
Nice=10
IOSchedulingClass=idle
{HARDENING}"""


def render_backup_timer(layout: Layout) -> str:
    return f"""{MANAGED.format(unit=layout.backup_timer.name)}
[Unit]
Description=Daily Crypto Helper database backup

[Timer]
OnCalendar=daily
RandomizedDelaySec=30m
# Run at the next boot if the VM was off when the backup was due.
Persistent=true

[Install]
WantedBy=timers.target
"""


def render_config(layout: Layout) -> str:
    return f"""# Crypto Helper configuration, read by the service and the `crypto-helper` command.
# After changing it: sudo crypto-helper service restart
# All settings: WIKI/reference/configuration.md

BOT_DATABASE_URL=sqlite:///{layout.db}
BOT_STATE_DIR={layout.state}
BOT_SECRET_KEY_FILE={layout.key}

# Listen only on this machine. Reach it from elsewhere through an SSH tunnel, Tailscale,
# NetBird or Cloudflare Access, never a bare open port.
BOT_HOST=127.0.0.1
BOT_PORT={layout.port}

# Set to true once the dashboard is served over HTTPS (e.g. tailscale serve).
BOT_COOKIE_SECURE=false

# BOT_SESSION_HOURS=12
# BOT_MAX_FAILED_LOGINS=5
# BOT_LOCKOUT_MINUTES=15
# BOT_PRICE_PROVIDER=coingecko
"""
