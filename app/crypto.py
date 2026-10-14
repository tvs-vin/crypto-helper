"""Encryption of secrets at rest, using Fernet from the `cryptography` package."""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings

__all__ = ["InvalidToken", "SecretBox", "load_secret_box"]


class SecretBox:
    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Raises InvalidToken if the data was encrypted with a different key."""
        return self._fernet.decrypt(token.encode()).decode()


def _read_or_create_key(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = Fernet.generate_key()
    # Create with 0600 from the start so the key is never readable by others, even briefly.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key + b"\n")
    return key


def load_secret_box(settings: Settings) -> SecretBox:
    if settings.secret_key:
        key = settings.secret_key.encode()
    else:
        key = _read_or_create_key(Path(settings.secret_key_file).expanduser())
    try:
        return SecretBox(key)
    except ValueError as e:
        raise SystemExit(
            "BOT_SECRET_KEY / secret key file is not a valid Fernet key "
            "(32 url-safe base64-encoded bytes)."
        ) from e
