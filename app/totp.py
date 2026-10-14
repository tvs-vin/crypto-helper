"""TOTP (authenticator-app codes) and recovery codes, built on pyotp and argon2."""

import hmac
import re
import secrets
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

ISSUER = "Crypto Helper"
STEP_SECONDS = 30
# Accept the previous and next 30-second window too, in case the phone's clock drifts.
DRIFT_STEPS = 1

RECOVERY_CODE_COUNT = 10
# No 0/o/1/l/i, so codes are easy to copy from paper. 10 chars of 31 = ~50 bits each.
_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
_TOTP_RE = re.compile(r"^\d{6}$")
_RECOVERY_RE = re.compile(rf"^[{_ALPHABET}]{{5}}-?[{_ALPHABET}]{{5}}$")

# Recovery codes are long random strings, so a lighter argon2 profile (OWASP minimum) is
# plenty and keeps checking all 10 codes at login fast.
_recovery_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def new_secret() -> str:
    return pyotp.random_base32()  # 32 base32 chars = 160 bits


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def normalize(code: str) -> str:
    return code.replace(" ", "").strip().lower()


def looks_like_totp(code: str) -> bool:
    return bool(_TOTP_RE.match(normalize(code)))


def verify_totp(secret: str, code: str, last_step: int | None, now: float | None = None):
    """Return the matched time step, or None.

    A code from a step at or before `last_step` is a replay and is refused, so a code
    seen over someone's shoulder can't be reused in its 30-second window.
    """
    code = normalize(code)
    if not _TOTP_RE.match(code):
        return None
    totp = pyotp.TOTP(secret)
    current = int((time.time() if now is None else now) // STEP_SECONDS)
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        expected = totp.at(step * STEP_SECONDS)
        if hmac.compare_digest(expected, code) and (last_step is None or step > last_step):
            return step
    return None


def new_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def canonical_recovery(code: str) -> str | None:
    code = normalize(code)
    if not _RECOVERY_RE.match(code):
        return None
    code = code.replace("-", "")
    return f"{code[:5]}-{code[5:]}"


def hash_recovery_code(code: str) -> str:
    return _recovery_hasher.hash(code)


def recovery_code_matches(code_hash: str, code: str) -> bool:
    try:
        return _recovery_hasher.verify(code_hash, code)
    except (VerificationError, InvalidHashError):
        return False
