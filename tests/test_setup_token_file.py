import stat

from app.config import Settings
from app.setup_token import read_setup_token, setup_token_path
from tests.conftest import PASSWORD, H


def test_token_file_written_private_on_first_launch(app, client):
    path = setup_token_path(app.state.settings)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_setup_token(app.state.settings) == app.state.setup_token


def test_token_file_removed_after_setup(app, ready):
    assert not setup_token_path(app.state.settings).exists()
    assert read_setup_token(app.state.settings) is None


def test_no_token_file_when_users_exist(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    db = tmp_path / "bot.db"
    s = Settings(database_url=f"sqlite:///{db}", _env_file=None)
    app1 = create_app(s)
    with TestClient(app1) as c:
        c.post(
            "/api/setup", json={"token": app1.state.setup_token, "password": PASSWORD}, headers=H
        )
    app2 = create_app(s)
    with TestClient(app2):
        assert app2.state.setup_token is None
        assert not setup_token_path(s).exists()
