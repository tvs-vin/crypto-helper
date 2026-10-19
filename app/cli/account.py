"""`crypto-helper account ...`"""

from sqlalchemy import select

from app import accounts, alerts
from app.cli.common import (
    PROG,
    CliError,
    UsageError,
    audit,
    find_user,
    load_settings,
    open_db,
    read_new_password,
)
from app.deps import effective_permissions, requires_2fa
from app.models import User
from app.timeutil import utcnow

ACCOUNT_USAGE = f"""usage:
  {PROG} account list
  {PROG} account <name> password [--stdin]   set a new password (asked for, never an argument)
  {PROG} account <name> unlock               clear a login lockout
  {PROG} account <name> 2fa reset            turn off 2FA and delete recovery codes
  {PROG} account <name> sessions revoke      sign the account out everywhere
  {PROG} account <name> new-password on|off  require a new password at next sign-in
  {PROG} account <name> require-2fa on|off   require two-factor login (super: always)"""

RULES = {"new-password": "must_change_password", "require-2fa": "require_2fa"}


def account_list() -> None:
    settings = load_settings()
    _, factory = open_db(settings)
    now = utcnow()
    with factory() as db:
        users = db.scalars(select(User).order_by(User.id)).all()
        rows = [("ID", "USERNAME", "ACTIVE", "2FA", "LOCKED", "PERMISSIONS")]
        for u in users:
            perms = "ALL (super)" if u.is_super else ", ".join(sorted(effective_permissions(u)))
            locked = u.locked_until is not None and u.locked_until > now
            rows.append(
                (
                    str(u.id),
                    u.username,
                    "yes" if u.is_active else "no",
                    ("on" if u.totp_enabled else "off")
                    + (" (required)" if requires_2fa(u, settings) else "")
                    + (", new password due" if u.must_change_password else ""),
                    "yes" if locked else "no",
                    perms or "-",
                )
            )
    if len(rows) == 1:
        print(f"No accounts yet. Create `super` first: {PROG} setup token")
        return
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)) + "  " + r[-1])


def account_action(name: str, words: list[str]) -> None:
    action = " ".join(w for w in words if not w.startswith("-"))
    flags = [w for w in words if w.startswith("-")]
    allowed_flags = {"password": {"--stdin"}}.get(action, set())
    rules = {f"{k} {v}" for k in RULES for v in ("on", "off")}
    if action not in ("password", "unlock", "2fa reset", "sessions revoke", *rules) or (
        set(flags) - allowed_flags
    ):
        raise UsageError(ACCOUNT_USAGE)

    password = read_new_password("--stdin" in flags) if action == "password" else None
    _, factory = open_db(load_settings())
    with factory() as db:
        user = find_user(db, name)
        if action == "password":
            accounts.set_password(user, password)
            n = accounts.revoke_sessions(db, user)
            audit(db, "user.update", user, f"password reset; {n} sessions revoked")
            alerts.password_changed(db, None, user, by="the server's command line")
            msg = f"Password changed for {name}. {n} session(s) signed out."
        elif action == "unlock":
            accounts.unlock(user)
            audit(db, "user.update", user, "unlocked")
            msg = f"{name} is unlocked."
        elif action == "2fa reset":
            if not user.totp_enabled and not user.totp_secret:
                raise CliError(f"{name} doesn't have 2FA set up. Nothing to reset.")
            accounts.reset_2fa(db, user)
            n = accounts.revoke_sessions(db, user)
            audit(db, "2fa.reset", user, f"2FA and recovery codes removed; {n} sessions revoked")
            alerts.twofa_off(db, None, user, by="the server's command line")
            msg = (
                f"2FA is off for {name} and their recovery codes are deleted. "
                f"{n} session(s) signed out. They can set 2FA up again after logging in."
            )
        elif action in rules:
            rule, value = action.split()
            if user.is_super:
                raise CliError(
                    "super's rules are fixed: it always needs 2FA, and its password is "
                    f"changed with `{PROG} account super password`."
                )
            setattr(user, RULES[rule], value == "on")
            audit(db, "user.update", user, f"{RULES[rule]}={value == 'on'}")
            msg = {
                "new-password on": f"{name} must choose a new password at their next request.",
                "new-password off": f"{name} no longer has to choose a new password.",
                "require-2fa on": f"{name} must have two-factor login turned on to use the app.",
                "require-2fa off": f"{name} no longer has to use two-factor login.",
            }[action]
        else:  # sessions revoke
            n = accounts.revoke_sessions(db, user)
            audit(db, "user.update", user, f"{n} sessions revoked")
            msg = f"{n} session(s) signed out for {name}."
        db.commit()
    print(msg)


def run_account(words: list[str]) -> int:
    if not words or words[0] in ("-h", "--help"):
        print(ACCOUNT_USAGE)
        return 0 if words else 2
    if words == ["list"]:
        account_list()
    elif len(words) >= 2:
        account_action(words[0], words[1:])
    else:
        raise UsageError(ACCOUNT_USAGE)
    return 0
