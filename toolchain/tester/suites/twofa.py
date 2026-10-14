"""2FA checks. Only ever turns 2FA on for throwaway t_* users, never the real account."""

import time

from toolchain.tester.framework import PW, check, expect, expect_status


def _code(secret: str, steps_ahead: int = 1) -> str:
    import pyotp  # from the app's venv; the rest of the tester is stdlib only

    return pyotp.TOTP(secret).at(time.time() + steps_ahead * 30)


def _wrong(secret: str) -> str:
    return "000000" if _code(secret) != "000000" else "111111"


def _enrolled(ctx):
    """A throwaway user with 2FA on. Returns (name, client, secret, recovery codes)."""
    name, _ = ctx.make_user()
    c = ctx.as_user(name)
    r = c.post("/api/auth/totp/setup")
    expect_status(r, 200, "2FA setup")
    secret = r.json()["secret"]
    r = c.post("/api/auth/totp/enable", {"code": _code(secret, 0)})
    expect_status(r, 200, "2FA enable")
    return name, c, secret, r.json()["recovery_codes"]


def _login(ctx, name, otp=None):
    body = {"username": name, "password": PW}
    if otp is not None:
        body["totp"] = otp
    return ctx.client().post("/api/auth/login", body)


@check("twofa", "setup returns an otpauth link, is never cached, and needs a session")
def setup(ctx):
    expect_status(ctx.client().post("/api/auth/totp/setup"), 401, "setup without session")
    name, _ = ctx.make_user()
    r = ctx.as_user(name).post("/api/auth/totp/setup")
    expect_status(r, 200, "setup")
    data = r.json()
    expect(data["otpauth_uri"].startswith("otpauth://totp/"), "bad otpauth link")
    expect(r.headers.get("cache-control") == "no-store", "setup response may be cached")


@check("twofa", "enable needs a correct code and returns 10 recovery codes")
def enable(ctx):
    name, _ = ctx.make_user()
    c = ctx.as_user(name)
    secret = c.post("/api/auth/totp/setup").json()["secret"]
    expect_status(c.post("/api/auth/totp/enable", {"code": _wrong(secret)}), 400, "wrong code")
    r = c.post("/api/auth/totp/enable", {"code": _code(secret, 0)})
    expect_status(r, 200, "right code")
    expect(len(r.json()["recovery_codes"]) == 10, "expected 10 recovery codes")
    me = c.get("/api/auth/me").json()
    expect(me["totp_enabled"] and me["recovery_codes_left"] == 10, f"/me says {me}")


@check("twofa", "login asks for the code, accepts a right one, refuses a replay")
def login_flow(ctx):
    name, _, secret, _ = _enrolled(ctx)
    r = _login(ctx, name)
    expect_status(r, 401, "no code")
    expect(r.json().get("totp_required") is True, "no totp_required flag")
    code = _code(secret)
    expect_status(_login(ctx, name, code), 200, "right code")
    expect_status(_login(ctx, name, code), 401, "same code again (replay)")


@check("twofa", "wrong 2FA codes lock the account")
def wrong_codes_lock(ctx):
    name, _, secret, _ = _enrolled(ctx)
    for i in range(5):
        expect_status(_login(ctx, name, _wrong(secret)), 401, f"wrong code {i + 1}")
    expect_status(_login(ctx, name, _code(secret)), 401, "right code while locked")


@check("twofa", "recovery codes work once and can be replaced")
def recovery(ctx):
    name, c, _, codes = _enrolled(ctx)
    expect_status(_login(ctx, name, codes[0]), 200, "recovery code")
    expect_status(_login(ctx, name, codes[0]), 401, "same recovery code again")
    expect(c.get("/api/auth/me").json()["recovery_codes_left"] == 9, "count didn't drop")
    expect_status(
        c.post("/api/auth/totp/recovery-codes", {"password": "wrong-password-x"}),
        403,
        "regenerate with wrong password",
    )
    r = c.post("/api/auth/totp/recovery-codes", {"password": PW})
    expect_status(r, 200, "regenerate")
    expect_status(_login(ctx, name, codes[1]), 401, "old code after regenerating")
    expect_status(_login(ctx, name, r.json()["recovery_codes"][0]), 200, "new code")


@check("twofa", "disable needs the password, then login needs no code")
def disable(ctx):
    name, c, _, _ = _enrolled(ctx)
    expect_status(
        c.post("/api/auth/totp/disable", {"password": "wrong-password-x"}),
        403,
        "disable with wrong password",
    )
    expect_status(c.post("/api/auth/totp/disable", {"password": PW}), 200, "disable")
    expect_status(_login(ctx, name), 200, "login without code after disable")


@check("twofa", "2FA secrets and recovery codes never show up in the audit log")
def no_leaks(ctx):
    _, _, secret, codes = _enrolled(ctx)
    blob = ctx.admin.get("/api/audit?limit=1000").text
    for s in (secret, *codes):
        expect(s not in blob, "audit log contains a 2FA secret or recovery code")
