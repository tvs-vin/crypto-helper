"""The one-time first-launch token, kept in a 0600 file for `crypto-helper setup token`."""

import os
from pathlib import Path

from app.config import Settings


def setup_token_path(settings: Settings) -> Path:
    return Path(settings.state_dir) / "setup-token"


def write_setup_token(settings: Settings, token: str) -> None:
    path = setup_token_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")


def read_setup_token(settings: Settings) -> str | None:
    path = setup_token_path(settings)
    return path.read_text().strip() if path.exists() else None


def clear_setup_token(settings: Settings) -> None:
    setup_token_path(settings).unlink(missing_ok=True)
