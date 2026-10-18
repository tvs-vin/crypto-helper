"""`crypto-helper version` and `crypto-helper config show`."""

from importlib import metadata
from pathlib import Path

from app.cli.common import dim, load_settings, run
from app.cli.layout import current_layout

REPO = Path(__file__).resolve().parents[2]


def package_version() -> str:
    try:
        return metadata.version("crypto-helper")
    except metadata.PackageNotFoundError:
        return "0+unknown"


def source_dir() -> Path | None:
    """The git checkout this install came from: /opt/crypto-helper/src, or the dev repo."""
    layout = current_layout()
    for candidate in (layout.src, REPO):
        if (candidate / ".git").exists():
            return candidate
    return None


def git_info(src: Path) -> tuple[str, str] | None:
    head = run(["git", "-C", str(src), "rev-parse", "--short", "HEAD"], check=False)
    branch = run(["git", "-C", str(src), "rev-parse", "--abbrev-ref", "HEAD"], check=False)
    if head.returncode or branch.returncode:
        return None
    return branch.stdout.strip(), head.stdout.strip()


def version_string() -> str:
    src = source_dir()
    info = git_info(src) if src else None
    return package_version() + (f" ({info[0]} @ {info[1]})" if info else "")


def show_version() -> int:
    print(f"crypto-helper {version_string()}")
    return 0


SECRET_FIELDS = {"secret_key", "coingecko_api_key"}


def show_config() -> int:
    settings = load_settings()
    layout = current_layout()
    source = layout.config if layout.is_installed() else "environment / ./.env"
    print(dim(f"# effective settings (from {source}); secrets are hidden"))
    for name, value in settings.model_dump().items():
        if name in SECRET_FIELDS and value:
            value = "<set, hidden>"
        print(f"BOT_{name.upper()}={'' if value is None else value}")
    return 0
