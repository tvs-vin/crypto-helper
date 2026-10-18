"""10b: no secret reaches the servers' output (the systemd journal, in a real install).

Both servers are started the way the service starts them (`crypto-helper serve`, with its
logging), taken through everything that handles a secret, and then their whole output is
searched for every secret used.
"""

import json
import time
import urllib.error
import urllib.request

import pyotp
import pytest

from toolchain.tester.server import SpawnedServer


@pytest.fixture(scope="module")
def served():
    s = SpawnedServer(embed=True, cli=True)
    s.start()
    yield s
    s.stop()


def call(s, method, path, body=None, cookie=None, base=None):
    req = urllib.request.Request(
        (base or s.base_url) + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Requested-With": "fetch",
            **({"Cookie": cookie} if cookie else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, r.headers, json.loads(raw) if raw[:1] in (b"{", b"[") else raw
    except urllib.error.HTTPError as e:
        return e.code, e.headers, None


def test_no_secret_in_the_log(served):
    s = served
    secrets_used = {"setup token": s.token_file.read_text().strip(), "password": s.password}
    status, *_ = call(
        s, "POST", "/api/setup", {"token": secrets_used["setup token"], "password": s.password}
    )
    assert status in (200, 201)
    # A wrong password typed in, and a password typed into the username box.
    secrets_used["wrong password"] = "wrong-Password-4417-zz"
    call(
        s,
        "POST",
        "/api/auth/login",
        {"username": "super", "password": secrets_used["wrong password"]},
    )
    secrets_used["password as username"] = "My-Real-Passphrase-9931"
    call(
        s,
        "POST",
        "/api/auth/login",
        {"username": secrets_used["password as username"], "password": "x"},
    )
    _, headers, _ = call(
        s, "POST", "/api/auth/login", {"username": "super", "password": s.password}
    )
    cookie = headers["set-cookie"].split(";")[0]
    secrets_used["session token"] = cookie.split("=", 1)[1]

    # 2FA: the secret, a code, the recovery codes; signing in with one of them.
    _, _, setup = call(s, "POST", "/api/auth/totp/setup", {}, cookie)
    secrets_used["2FA secret"] = setup["secret"]
    _, _, enabled = call(
        s,
        "POST",
        "/api/auth/totp/enable",
        {"code": pyotp.TOTP(setup["secret"]).now(), "password": s.password},
        cookie,
    )
    codes = enabled["recovery_codes"]
    secrets_used |= {f"recovery code {i}": c for i, c in enumerate(codes)}
    status, headers, _ = call(
        s,
        "POST",
        "/api/auth/login",
        {"username": "super", "password": s.password, "totp": codes[0]},
    )
    assert status == 200
    cookie = headers["set-cookie"].split(";")[0]

    # A Discord webhook address (never contacted).
    hook = "https://discord.com/api/webhooks/123456789012345678/" + "LogTestToken_" + "Q" * 30
    secrets_used["webhook token"] = hook.rsplit("/", 1)[1]
    assert call(s, "PUT", "/api/notifications/channels/discord", {"url": hook}, cookie)[0] == 200

    # An embed link, opened on the embed server (page, picture, stylesheet).
    status, _, embed = call(
        s, "POST", "/api/embeds", {"name": "log test", "kind": "prices"}, cookie
    )
    assert status == 201, embed
    token = embed["url"].rsplit("/", 1)[1]
    secrets_used["embed token"] = token
    for suffix in ("", ".png", ".css"):
        status, *_ = call(s, "GET", f"/embed/{token}{suffix}", base=s.embed_url)
        assert status == 200, suffix

    # Something secret in a query string (like the terminal's one-time ticket).
    secrets_used["ticket"] = "TicketLike-" + "k" * 30
    call(s, "GET", f"/api/terminal/ws?ticket={secrets_used['ticket']}", cookie=cookie)

    # Changing the password.
    secrets_used["new password"] = "Brand-New-Passphrase-5521"
    status, *_ = call(
        s,
        "POST",
        "/api/auth/password",
        {"current_password": s.password, "new_password": secrets_used["new password"]},
        cookie,
    )
    assert status == 200

    time.sleep(0.5)  # let the last lines arrive
    log = "".join(s.output)
    leaked = [name for name, value in secrets_used.items() if value in log]
    assert not leaked, f"found in the log: {leaked}"
    assert "GET /embed/… HTTP" in log and "?… HTTP" in log  # the requests were still logged
