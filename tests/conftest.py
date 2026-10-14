import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PASSWORD = "correct-horse-battery"
H = {"X-Requested-With": "fetch"}


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
