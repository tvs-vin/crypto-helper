"""A tiny HTTP client (stdlib only) that behaves like one browser: it keeps its own cookies."""

import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar


class Response:
    def __init__(self, status: int, headers, body: bytes):
        self.status = status
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.raw_headers = headers
        self.text = body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text) if self.text else None


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, method: str, path: str, body=None, *, csrf: bool = True, headers=None):
        data = None
        hdrs = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        if csrf and method not in ("GET", "HEAD"):
            hdrs["X-Requested-With"] = "fetch"
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=hdrs)
        try:
            with self.opener.open(req, timeout=15) as r:
                return Response(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            return Response(e.code, e.headers, e.read())

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body, **kw)

    def put(self, path, body=None, **kw):
        return self.request("PUT", path, body, **kw)

    def patch(self, path, body=None, **kw):
        return self.request("PATCH", path, body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def login(self, username: str, password: str) -> Response:
        return self.post("/api/auth/login", {"username": username, "password": password})

    def session_cookie(self):
        return next((c for c in self.cookies if c.name == "session"), None)
