import os

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PASSWORD = "correct-horse-battery"
H = {"X-Requested-With": "fetch"}


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Keep tests away from real keys and state: every Settings() sees these."""
    monkeypatch.setenv("BOT_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("BOT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BOT_SECRET_KEY_FILE", str(tmp_path / "no-such-dir" / "secret.key"))
    # Hide any real installed service (/etc/crypto-helper, ...) from the CLI code under test;
    # otherwise running as root would make it switch the test process to the service user.
    monkeypatch.setenv("CRYPTO_HELPER_ROOT", str(tmp_path / "fake-root"))
    monkeypatch.delenv("CRYPTO_HELPER_CONFIG", raising=False)
    # Tests drive prices and history explicitly; no background job, no real CoinGecko.
    monkeypatch.setenv("BOT_PRICE_BACKGROUND", "false")
    monkeypatch.setenv("BOT_NOTIFY_BACKGROUND", "false")  # tests run deliveries themselves
    monkeypatch.setenv("BOT_SYNC_BACKGROUND", "false")  # and syncs
    monkeypatch.setenv("BOT_SYNC_DEMO", "true")  # the pretend exchange (no network)
    # super needs 2FA before anything else on a real install; tests sign super in with a
    # password only (tests/test_account_rules.py switches it back on).
    monkeypatch.setenv("BOT_SUPER_REQUIRES_TWO_FACTOR", "false")
    monkeypatch.setenv("BOT_PRICE_PROVIDER", "mock")
    # TestClient's client address is "testclient", not an IP; network checks have own tests.
    monkeypatch.setenv("BOT_ALLOWED_NETWORKS", "*")
    monkeypatch.delenv("CRYPTO_HELPER_ELEVATED", raising=False)

    # A test must never really replace the test process (e.g. by re-running under sudo).
    def no_exec(*args, **kwargs):
        raise RuntimeError(f"test tried to exec {args[:2]}")

    monkeypatch.setattr(os, "execv", no_exec)
    monkeypatch.setattr(os, "execvp", no_exec)


@pytest.fixture
def app():
    return create_app(Settings(database_url="sqlite://", price_provider="mock", _env_file=None))


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def ready(client, app):
    """A client with `super` already created through the real setup flow."""
    r = client.post(
        "/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H
    )
    assert r.status_code == 201
    return client


@pytest.fixture
def logged_in(ready):
    r = ready.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
    assert r.status_code == 200
    return ready


# Tests that set file owners (root:crypto-helper) can only run as root. This VM runs the tests
# as root and so does CI; elsewhere they're skipped rather than failing.
needs_root = pytest.mark.skipif(
    os.geteuid() != 0, reason="sets file owners: needs root (the VM and CI run tests as root)"
)
