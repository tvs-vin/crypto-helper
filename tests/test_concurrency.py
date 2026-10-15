"""Many requests at once against a real SQLite file (the browser fires saves in parallel)."""

import threading

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import PASSWORD, H


def test_parallel_writes_never_hit_database_is_locked(tmp_path):
    """Regression: two writes that both read first (the session check) deadlocked SQLite's
    lock upgrade and one failed at once with "database is locked" (HTTP 500), e.g. the
    desktop saving the theme and the layout at the same moment."""
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/c.db", _env_file=None))
    with TestClient(app) as admin:
        admin.post(
            "/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H
        )
        admin.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
        statuses = []
        start = threading.Barrier(16)

        def worker(i):
            c = TestClient(app)
            c.cookies = admin.cookies
            start.wait()
            for j in range(6):
                body = (
                    {"theme": ["dark", "light"][j % 2]}
                    if i % 2
                    else {
                        "layout": {
                            "windows": [{"panel": "wallets", "x": i, "y": j, "w": 500, "h": 400}]
                        }
                    }
                )
                statuses.append(c.patch("/api/me/preferences", json=body, headers=H).status_code)
                statuses.append(c.get("/api/auth/me").status_code)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
    assert len(statuses) == 16 * 12
    assert set(statuses) == {200}, sorted(set(statuses))
