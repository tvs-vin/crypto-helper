"""Automatic security notifications (milestone 9c): things that happened to an account.

Each goes to the account itself, and the important ones (lockouts, 2FA turned off, a terminal
opened) to the admins too. They're added to the caller's transaction like any notification, so
nothing is announced for something that was rolled back. Never put a secret in the text: these
can go to Discord.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import notifications as nt
from app.models import AuditLog, User

IF_NOT_YOU = "If this wasn't you, change your password now (Settings → Account)."


def _hub(request):
    return getattr(request.app.state, "hub", None) if request is not None else None


def _ip(request) -> str:
    return (request.client.host if request is not None and request.client else None) or "unknown"


def tell(db: DbSession, request, user: User, title: str, body: str, level: str = "warning"):
    """To the account itself."""
    nt.notify(
        db,
        _hub(request),
        [user],
        category="security",
        title=title,
        body=body,
        level=level,
        link="settings",
    )


def tell_admins(db: DbSession, request, about: User, title: str, body: str, level="warning"):
    """To every admin except the person it's about (they get their own)."""
    others = [a for a in nt.admins(db) if a.id != about.id]
    nt.notify(
        db,
        _hub(request),
        others,
        category="security",
        title=title,
        body=body,
        level=level,
        link="audit",
    )


# ---- events ---------------------------------------------------------------------------------


def is_new_device(db: DbSession, user: User, ip: str | None, device: str) -> bool:
    """True when this account has signed in before, but never from this address with this kind
    of device. (Sign-ins from before 9c didn't record the device: those match on address.)"""
    seen = db.execute(
        select(AuditLog.source_ip, AuditLog.detail)
        .where(AuditLog.user_id == user.id, AuditLog.action == "login.ok")
        .distinct()
    ).all()
    if not seen:
        return False  # the very first sign-in isn't news
    return not any(s_ip == ip and detail in (device, "") for s_ip, detail in seen)


def signed_in(db: DbSession, request, user: User, device: str) -> None:
    """Call before the login.ok audit entry is written."""
    ip = _ip(request)
    if is_new_device(db, user, ip if ip != "unknown" else None, device):
        tell(
            db,
            request,
            user,
            "New sign-in to your account",
            f"{device} from {ip}. {IF_NOT_YOU} Settings → Account → Sessions signs it out.",
        )


def locked_out(db: DbSession, request, user: User, attempts: int, minutes: int) -> None:
    ip = _ip(request)
    tell(
        db,
        request,
        user,
        "Your account was locked",
        f"{attempts} wrong passwords or codes in a row, the last from {ip}. It unlocks by "
        f"itself in {minutes} minutes. {IF_NOT_YOU}",
    )
    tell_admins(
        db,
        request,
        user,
        f"{user.username} was locked out",
        f"{attempts} failed attempts in a row, the last from {ip}. Unlocks in "
        f"{minutes} minutes (or: crypto-helper account {user.username} unlock).",
    )


def recovery_code_used(db: DbSession, request, user: User, left: int) -> None:
    more = " Make new ones soon (Settings → Account)." if left <= 3 else ""
    tell(
        db,
        request,
        user,
        "A recovery code was used",
        f"To sign in from {_ip(request)}. {left} left.{more} {IF_NOT_YOU}",
    )


def password_changed(db: DbSession, request, user: User, by: str | None = None) -> None:
    """`by`: who did it, when it wasn't the account itself (an admin, or the server's CLI)."""
    if by is None:
        tell(
            db,
            request,
            user,
            "Your password was changed",
            f"From {_ip(request)}. Your other sessions were signed out. {IF_NOT_YOU}",
        )
    else:
        tell(
            db,
            request,
            user,
            "Your password was reset",
            f"By {by}. All your sessions were signed out. If you didn't ask for this, "
            "tell your admin.",
        )


def twofa_off(db: DbSession, request, user: User, by: str | None = None) -> None:
    how = f"by {by}" if by else f"from {_ip(request)}"
    tell(
        db,
        request,
        user,
        "Two-factor login was turned off",
        f"Turned off {how}. Your account is now protected by the password alone. "
        "Turn it back on in Settings → Account.",
        level="critical",
    )
    tell_admins(
        db, request, user, f"{user.username} has no two-factor login now", f"Turned off {how}."
    )


def terminal_opened(db: DbSession, request, user: User) -> None:
    tell_admins(
        db,
        request,
        user,
        f"{user.username} opened a terminal",
        f"A root-capable login prompt, from {_ip(request)}.",
        level="info",
    )
