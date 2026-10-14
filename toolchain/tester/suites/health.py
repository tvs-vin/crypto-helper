import secrets

from toolchain.tester.framework import check, expect, expect_status

HEADERS = {
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}


@check("health", "server answers setup status")
def status(ctx):
    r = ctx.client().get("/api/setup/status")
    expect_status(r, 200, "GET /api/setup/status")
    expect(r.json() == {"setup_required": False}, f"unexpected body {r.text}")


@check("health", "security headers on 200, 404 and 403 responses")
def headers(ctx):
    c = ctx.client()
    for r in (
        c.get("/api/setup/status"),
        c.get("/no-such-page"),
        c.post("/api/auth/login", {}, csrf=False),
    ):
        for name, value in HEADERS.items():
            expect(r.headers.get(name) == value, f"{name} missing or wrong on HTTP {r.status}")
        csp = r.headers.get("content-security-policy", "")
        expect("default-src 'self'" in csp, f"weak or missing CSP: {csp!r}")
        expect("unsafe-inline" not in csp, "CSP allows unsafe-inline")


@check("health", "CSRF guard: POST without X-Requested-With is refused")
def csrf_missing(ctx):
    r = ctx.client().post("/api/auth/login", {"username": "x", "password": "y"}, csrf=False)
    expect_status(r, 403, "POST without header")


@check("health", "CSRF guard: wrong X-Requested-With value is refused")
def csrf_wrong(ctx):
    r = ctx.client().post(
        "/api/auth/login", {}, csrf=False, headers={"X-Requested-With": "XMLHttpRequest"}
    )
    expect_status(r, 403, "POST with wrong header value")


@check("health", "no CORS headers for a foreign origin")
def no_cors(ctx):
    r = ctx.client().get("/api/setup/status", headers={"Origin": "https://evil.example"})
    expect("access-control-allow-origin" not in r.headers, "server sent CORS headers")


@check("health", "API docs are not exposed")
def docs_hidden(ctx):
    c = ctx.client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        expect_status(c.get(path), 404, path)


@check("health", "setup cannot be run again")
def setup_closed(ctx):
    r = ctx.client().post(
        "/api/setup", {"token": secrets.token_urlsafe(24), "password": "whatever-long-enough"}
    )
    expect_status(r, 409, "second setup")
