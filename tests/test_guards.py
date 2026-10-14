import pytest

from tests.conftest import PASSWORD


@pytest.mark.parametrize(
    "path", ["/api/auth/login", "/api/auth/logout", "/api/auth/password", "/api/setup"]
)
def test_csrf_header_required_on_post(client, path):
    r = client.post(path, json={"username": "super", "password": PASSWORD})
    assert r.status_code == 403


def test_csrf_header_must_have_the_right_value(client):
    r = client.post("/api/auth/login", json={}, headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 403


def test_get_needs_no_csrf_header(client):
    assert client.get("/api/setup/status").status_code == 200


def test_security_headers_on_every_response(client):
    for r in (
        client.get("/api/setup/status"),
        client.get("/nope"),
        client.post("/api/auth/login", json={}),
    ):
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        csp = r.headers["content-security-policy"]
        assert "default-src 'self'" in csp and "unsafe-inline" not in csp


def test_no_cors_headers(client):
    r = client.get("/api/setup/status", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_api_docs_are_not_exposed(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
