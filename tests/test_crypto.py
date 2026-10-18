import stat

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.crypto import InvalidToken, SecretBox, load_secret_box


def settings(**kw):
    return Settings(_env_file=None, **{"secret_key": None, **kw})


def test_key_file_is_created_private_and_reused(tmp_path):
    path = tmp_path / "conf" / "secret.key"
    box = load_secret_box(settings(secret_key_file=str(path)))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    token = box.encrypt("hello")
    assert "hello" not in token
    again = load_secret_box(settings(secret_key_file=str(path)))
    assert again.decrypt(token) == "hello"


def test_env_key_wins_over_file(tmp_path):
    key = Fernet.generate_key().decode()
    path = tmp_path / "secret.key"
    box = load_secret_box(settings(secret_key=key, secret_key_file=str(path)))
    assert not path.exists()
    assert SecretBox(key.encode()).decrypt(box.encrypt("x")) == "x"


def test_invalid_key_is_a_clear_error():
    with pytest.raises(SystemExit, match="not a valid Fernet key"):
        load_secret_box(settings(secret_key="too-short"))


def test_wrong_key_cannot_decrypt():
    a, b = SecretBox(Fernet.generate_key()), SecretBox(Fernet.generate_key())
    with pytest.raises(InvalidToken):
        b.decrypt(a.encrypt("secret"))
