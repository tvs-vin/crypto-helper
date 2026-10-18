import time

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import totp
from app.crypto import SecretBox
from app.models import AuditLog, RecoveryCode, User
from tests.conftest import PASSWORD, H
from tests.test_users import PW2, as_user, create


def code(secret: str, offset_steps: int = 1) -> str:
    """A valid code for a *later* window, so it never collides with the one used to enable."""
    return pyotp.TOTP(secret).at(time.time() + offset_steps * 30)


def enrol(client, password=PASSWORD) -> tuple[str, list[str]]:
    r = client.post("/api/auth/totp/setup", headers=H)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    body = {"code": code(secret, 0), "password": password}
    r = client.post("/api/auth/totp/enable", json=body, headers=H)
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def login(client, username="super", password=PASSWORD, otp=None):
    body = {"username": username, "password": password}
    if otp is not None:
        body["totp"] = otp
    return client.post("/api/auth/login", json=body, headers=H)


def stored_user(app, username="super") -> User:
    with app.state.session_factory() as db:
        return db.scalar(select(User).where(User.username == username))


def audit_blob(app) -> str:
    with app.state.session_factory() as db:
        return " ".join(f"{r.action} {r.detail} {r.username}" for r in db.scalars(select(AuditLog)))


# ---- pure TOTP logic ---------------------------------------------------------------------


def test_verify_accepts_one_step_of_drift_either_side():
    secret = totp.new_secret()
    now = 1_800_000_015.0
    base = int(now // 30)
    t = pyotp.TOTP(secret)
    for delta in (-1, 0, 1):
        assert totp.verify_totp(secret, t.at((base + delta) * 30), None, now) == base + delta
    for delta in (-2, 2):
        assert totp.verify_totp(secret, t.at((base + delta) * 30), None, now) is None


def test_verify_refuses_replay_and_junk():
    secret = totp.new_secret()
    now = 1_800_000_015.0
    step = int(now // 30)
    good = pyotp.TOTP(secret).at(step * 30)
    assert totp.verify_totp(secret, good, step, now) is None  # same step = replay
    assert totp.verify_totp(secret, good, step - 1, now) == step
    assert totp.verify_totp(secret, "12345", None, now) is None
    assert totp.verify_totp(secret, "abcdef", None, now) is None
    assert totp.verify_totp(secret, good[:3] + " " + good[3:], None, now) == step  # spaces ok


def test_recovery_code_format_and_normalisation():
    codes = totp.new_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    for c in codes:
        assert len(c) == 11 and c[5] == "-"
        assert totp.canonical_recovery(c.upper().replace("-", "")) == c
    assert totp.canonical_recovery("0oo1l-iiiii") is None  # ambiguous characters never used


# ---- enrolment ----------------------------------------------------------------------------


def test_totp_endpoints_need_a_session(ready):
    for path in (
        "/api/auth/totp/setup",
        "/api/auth/totp/enable",
        "/api/auth/totp/disable",
        "/api/auth/totp/recovery-codes",
    ):
        assert (
            ready.post(path, json={"code": "123456", "password": "x"}, headers=H).status_code == 401
        )


def test_setup_returns_secret_and_uri_and_stores_it_encrypted(logged_in, app):
    r = logged_in.post("/api/auth/totp/setup", headers=H)
    assert r.status_code == 200
    data = r.json()
    assert data["otpauth_uri"].startswith("otpauth://totp/Crypto%20Helper:super?")
    assert f"secret={data['secret']}" in data["otpauth_uri"]
    assert r.headers["cache-control"] == "no-store"
    user = stored_user(app)
    assert user.totp_secret and data["secret"] not in user.totp_secret
    assert app.state.secret_box.decrypt(user.totp_secret) == data["secret"]
    assert user.totp_enabled is False  # pending until confirmed


def test_setup_again_replaces_pending_secret(logged_in):
    a = logged_in.post("/api/auth/totp/setup", headers=H).json()["secret"]
    b = logged_in.post("/api/auth/totp/setup", headers=H).json()["secret"]
    assert a != b
    r = logged_in.post(
        "/api/auth/totp/enable", json={"code": code(a, 0), "password": PASSWORD}, headers=H
    )
    assert r.status_code == 400  # the old secret no longer counts


def test_enable_needs_setup_and_a_correct_code(logged_in):
    assert (
        logged_in.post(
            "/api/auth/totp/enable", json={"code": "123456", "password": PASSWORD}, headers=H
        ).status_code
        == 400
    )
    secret = logged_in.post("/api/auth/totp/setup", headers=H).json()["secret"]
    wrong = "000000" if code(secret, 0) != "000000" else "111111"
    assert (
        logged_in.post(
            "/api/auth/totp/enable", json={"code": wrong, "password": PASSWORD}, headers=H
        ).status_code
        == 400
    )


def test_enable_issues_ten_recovery_codes_and_updates_me(logged_in, app):
    _, codes = enrol(logged_in)
    assert len(codes) == 10
    me = logged_in.get("/api/auth/me").json()
    assert me["totp_enabled"] is True and me["recovery_codes_left"] == 10
    with app.state.session_factory() as db:
        hashes = [r.code_hash for r in db.scalars(select(RecoveryCode))]
    assert len(hashes) == 10 and all(h.startswith("$argon2id$") for h in hashes)
    assert not set(codes) & set(hashes)


def test_enable_and_setup_refused_when_already_on(logged_in):
    enrol(logged_in)
    assert logged_in.post("/api/auth/totp/setup", headers=H).status_code == 409
    assert (
        logged_in.post(
            "/api/auth/totp/enable", json={"code": "123456", "password": PASSWORD}, headers=H
        ).status_code
        == 409
    )


def test_enable_signs_out_other_sessions(logged_in, app):
    other = TestClient(app)
    assert login(other).status_code == 200
    enrol(logged_in)
    assert other.get("/api/auth/me").status_code == 401
    assert logged_in.get("/api/auth/me").status_code == 200


# ---- login with 2FA -----------------------------------------------------------------------


def test_login_asks_for_code_after_correct_password(logged_in, app):
    enrol(logged_in)
    r = login(TestClient(app))
    assert r.status_code == 401
    assert r.json() == {"detail": "2FA code required", "totp_required": True}
    assert "set-cookie" not in r.headers


def test_wrong_password_does_not_reveal_2fa(logged_in, app):
    enrol(logged_in)
    r = login(TestClient(app), password="wrong-password-123", otp="123456")
    assert r.status_code == 401 and r.json() == {"detail": "Invalid username or password"}


def test_missing_code_does_not_count_toward_lockout(logged_in, app):
    secret, _ = enrol(logged_in)
    c = TestClient(app)
    for _ in range(7):
        assert login(c).status_code == 401
    assert login(c, otp=code(secret)).status_code == 200


def test_login_with_code(logged_in, app):
    secret, _ = enrol(logged_in)
    r = login(TestClient(app), otp=code(secret))
    assert r.status_code == 200 and r.json()["totp_setup_recommended"] is False


def test_code_cannot_be_replayed(logged_in, app):
    secret, _ = enrol(logged_in)
    c = code(secret)
    assert login(TestClient(app), otp=c).status_code == 200
    r = login(TestClient(app), otp=c)
    assert r.status_code == 401 and r.json()["detail"] == "Invalid 2FA code"


def test_wrong_codes_lock_the_account(logged_in, app):
    secret, _ = enrol(logged_in)
    c = TestClient(app)
    good = code(secret)
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(5):
        assert login(c, otp=wrong).status_code == 401
    assert "login.lockout" in audit_blob(app)
    r = login(c, otp=good)
    assert r.status_code == 401 and r.json() == {"detail": "Invalid username or password"}


def test_super_is_nudged_to_enable_2fa_but_others_are_not(logged_in, app):
    assert login(TestClient(app)).json()["totp_setup_recommended"] is True
    create(logged_in, "bob")
    r = login(TestClient(app), "bob", PW2)
    assert r.json()["totp_setup_recommended"] is False


# ---- recovery codes ----------------------------------------------------------------------


def test_recovery_code_logs_in_once(logged_in, app):
    _, codes = enrol(logged_in)
    assert login(TestClient(app), otp=codes[0]).status_code == 200
    assert login(TestClient(app), otp=codes[0]).status_code == 401
    me = logged_in.get("/api/auth/me").json()
    assert me["recovery_codes_left"] == 9
    assert "2fa.recovery_used 9 codes left" in audit_blob(app)


def test_recovery_code_is_forgiving_about_case_and_dash(logged_in, app):
    _, codes = enrol(logged_in)
    assert login(TestClient(app), otp=codes[1].upper().replace("-", "")).status_code == 200


def test_regenerate_recovery_codes(logged_in, app):
    _, old = enrol(logged_in)
    bad = logged_in.post(
        "/api/auth/totp/recovery-codes", json={"password": "nope-nope-nope"}, headers=H
    )
    assert bad.status_code == 403
    r = logged_in.post("/api/auth/totp/recovery-codes", json={"password": PASSWORD}, headers=H)
    assert r.status_code == 200
    new = r.json()["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    assert login(TestClient(app), otp=old[0]).status_code == 401
    assert login(TestClient(app), otp=new[0]).status_code == 200


def test_recovery_codes_need_2fa_enabled(logged_in):
    r = logged_in.post("/api/auth/totp/recovery-codes", json={"password": PASSWORD}, headers=H)
    assert r.status_code == 400


def test_recovery_still_works_if_the_secret_key_changes(logged_in, app):
    """Losing the encryption key breaks TOTP, but hashed recovery codes still get you in."""
    from cryptography.fernet import Fernet

    secret, codes = enrol(logged_in)
    app.state.secret_box = SecretBox(Fernet.generate_key())
    assert login(TestClient(app), otp=code(secret)).status_code == 401
    assert login(TestClient(app), otp=codes[0]).status_code == 200


# ---- disable -----------------------------------------------------------------------------


def test_disable_needs_password_and_clears_everything(logged_in, app):
    enrol(logged_in)
    r = logged_in.post("/api/auth/totp/disable", json={"password": "nope-nope-nope"}, headers=H)
    assert r.status_code == 403
    r = logged_in.post("/api/auth/totp/disable", json={"password": PASSWORD}, headers=H)
    assert r.status_code == 200
    user = stored_user(app)
    assert not user.totp_enabled and user.totp_secret is None and user.totp_last_step is None
    with app.state.session_factory() as db:
        assert db.scalar(select(RecoveryCode)) is None
    assert login(TestClient(app)).status_code == 200


def test_disable_when_off_is_400(logged_in):
    r = logged_in.post("/api/auth/totp/disable", json={"password": PASSWORD}, headers=H)
    assert r.status_code == 400


def test_wrong_password_on_disable_counts_toward_lockout(logged_in, app):
    enrol(logged_in)
    for _ in range(5):
        logged_in.post("/api/auth/totp/disable", json={"password": "nope-nope-nope"}, headers=H)
    assert "login.lockout" in audit_blob(app)


# ---- no leaks ----------------------------------------------------------------------------


def test_secrets_never_leak_into_audit_me_or_user_list(logged_in, app):
    secret, codes = enrol(logged_in)
    create(logged_in, "bob")
    bob = as_user(app, "bob")
    s2, codes2 = enrol(bob, PW2)
    login(TestClient(app), otp=codes[0])
    blob = audit_blob(app)
    listing = logged_in.get("/api/users").text
    me = logged_in.get("/api/auth/me").text
    for s in [secret, s2, *codes, *codes2]:
        assert s not in blob and s not in listing and s not in me
    actions = blob.split()
    for a in ("2fa.setup", "2fa.enable", "2fa.recovery_used"):
        assert a in actions


@pytest.mark.parametrize("path", ["/api/auth/me", "/api/users", "/api/setup/status"])
def test_api_responses_are_not_cached(logged_in, path):
    assert logged_in.get(path).headers["cache-control"] == "no-store"


def test_enable_asks_for_the_password(logged_in, app):
    """A stolen session alone can't put someone else's authenticator on the account."""
    secret = logged_in.post("/api/auth/totp/setup", headers=H).json()["secret"]
    body = {"code": code(secret, 0), "password": "not-the-password"}
    assert logged_in.post("/api/auth/totp/enable", json=body, headers=H).status_code == 403
    assert stored_user(app).totp_enabled is False
    assert stored_user(app).failed_logins == 1  # counts toward lockout, like the others
    missing = {"code": code(secret, 0)}
    assert logged_in.post("/api/auth/totp/enable", json=missing, headers=H).status_code == 422
