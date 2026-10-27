"""Live trading foundations (phase 4, milestone 13a): which exchanges may trade live, each
person's cap, and the rules for trading keys. Nothing here places an order (13b, 13c).

- **Switches:** live trading is off for every exchange until super switches it on (Services).
  Anyone with `services.manage` may switch one off: stopping is easy, starting deliberate.
- **Caps:** the most a person's live bots may control, in USD. Unset: `DEFAULT_CAP`. An admin
  sets a person's cap and a ceiling; with `live.cap` a person may change their own cap up to
  the ceiling. Raising a cap or ceiling needs a 2FA code from whoever raises it. There's no
  maximum in the code (the owner's choice, 2026-10-27).
- **Trading keys:** may read and trade, never withdraw (hard rule #2). Checked with the
  exchange's own permission calls; refused if it can withdraw or can't trade; if the exchange
  can't say whether it can withdraw, the person must confirm what they ticked. Personal keys
  are their owner's alone; shared keys need `live.keys.shared` to make or use.
"""

from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.deps import effective_permissions
from app.models import AppSetting, TradingKey, User

DEFAULT_CAP = Decimal("150")
SWITCHES_KEY = "live_exchanges"
CAP_DECIMALS = Decimal("0.01")


class TradingError(Exception):
    def __init__(self, status: int, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


# ---- the switches ----------------------------------------------------------------------------


def switches(db: DbSession) -> dict[str, bool]:
    row = db.get(AppSetting, SWITCHES_KEY)
    return dict(row.value) if row else {}


def enabled(db: DbSession, exchange_id: str) -> bool:
    return bool(switches(db).get(exchange_id))


def set_switch(db: DbSession, exchange_id: str, on: bool, actor: User) -> None:
    """On: super only, with 2FA turned on. Off: whoever may manage services (checked by the
    caller)."""
    if on and not actor.is_super:
        raise TradingError(403, "Only super can switch live trading on")
    if on and not actor.totp_enabled:
        raise TradingError(403, "Turn on two-factor login first")
    value = {**switches(db), exchange_id: on}
    row = db.get(AppSetting, SWITCHES_KEY)
    if row is None:
        db.add(AppSetting(key=SWITCHES_KEY, value=value, updated_by=actor.username))
    else:
        row.value, row.updated_by = value, actor.username


def all_off(db: DbSession, by: str) -> list[str]:
    """Switch live trading off everywhere (the CLI's `live off`). Returns what was on."""
    was = [k for k, v in switches(db).items() if v]
    row = db.get(AppSetting, SWITCHES_KEY)
    if row is not None:
        row.value, row.updated_by = {k: False for k in row.value}, by
    return was


# ---- caps ------------------------------------------------------------------------------------


def parse_cap(text: str | None, what: str = "The cap") -> Decimal | None:
    """None/"" -> None (unset). Otherwise a positive amount of dollars with cents at most."""
    if text is None or str(text).strip() == "":
        return None
    if not isinstance(text, str):  # JSON numbers are refused, like every amount in the app
        raise TradingError(422, f'{what} must be text, like "150"')
    try:
        v = Decimal(text.strip().replace(",", "").removeprefix("$"))
    except InvalidOperation:
        raise TradingError(422, f"{what} must be an amount of dollars, like 150") from None
    if not v.is_finite() or v <= 0 or v != v.quantize(CAP_DECIMALS):
        raise TradingError(422, f"{what} must be more than 0, with cents at most")
    return v


def cap_of(user: User) -> Decimal:
    return Decimal(user.live_cap) if user.live_cap else DEFAULT_CAP


def ceiling_of(user: User) -> Decimal | None:
    return Decimal(user.live_cap_ceiling) if user.live_cap_ceiling else None


def caps_out(user: User) -> dict:
    ceiling = ceiling_of(user)
    return {
        "cap": str(cap_of(user)),
        "cap_is_default": user.live_cap is None,
        "ceiling": str(ceiling) if ceiling is not None else None,
        "default": str(DEFAULT_CAP),
        "currency": "usd",
    }


def raises(old: Decimal | None, new: Decimal | None) -> bool:
    """Does going from old to new allow more money? (None as a ceiling means no ceiling.)"""
    if new is None:
        return old is not None
    return old is not None and new > old


def set_own_cap(user: User, cap: Decimal) -> Decimal:
    """A person with `live.cap` changing their own cap: never above their ceiling."""
    ceiling = ceiling_of(user)
    if ceiling is not None and cap > ceiling:
        raise TradingError(403, f"Your ceiling is ${ceiling}: an admin can raise it")
    old = cap_of(user)
    user.live_cap = str(cap)
    return old


def set_caps(target: User, cap: Decimal | None, ceiling: Decimal | None) -> None:
    """An admin setting someone's cap and ceiling. A cap above the ceiling is refused; setting a
    ceiling below the current cap brings the cap down to it."""
    if cap is not None and ceiling is not None and cap > ceiling:
        raise TradingError(422, "The cap can't be above the ceiling")
    target.live_cap = str(cap) if cap is not None else None
    target.live_cap_ceiling = str(ceiling) if ceiling is not None else None
    if ceiling is not None and cap_of(target) > ceiling:
        target.live_cap = str(ceiling)


# ---- trading keys ----------------------------------------------------------------------------


def verdict(check, confirmed: bool, who: str, exchange) -> dict:
    """What to store about a checked key, or refuse it. `check` is a `TradeCheck`."""
    if check.can_withdraw:
        raise TradingError(
            422,
            f"{exchange.name} says this key can withdraw or move funds. Delete it on "
            f"{exchange.name} and make a new one without that permission: Crypto Helper never "
            "uses a key that can move money off the exchange.",
        )
    if check.can_trade is False:
        raise TradingError(
            422, f"{exchange.name} says this key can't trade: tick the trading permission"
        )
    confirmed_by = None
    if check.can_withdraw is None:
        if not confirmed:
            raise TradingError(
                409,
                f"{check.summary}. Check the key's permissions on {exchange.name} and confirm.",
                {"confirm": exchange.trading_confirm_text},
            )
        confirmed_by = who
    return {
        "can_trade": check.can_trade,
        "can_withdraw": check.can_withdraw,
        "ip_locked": check.ip_locked,
        "summary": check.summary,
        "confirmed_by": confirmed_by,
    }


def describe(check: dict) -> str:
    parts = []
    if check.get("can_withdraw") is False:
        parts.append("can't withdraw (checked)")
    elif check.get("confirmed_by"):
        parts.append(f"no withdrawals (confirmed by {check['confirmed_by']})")
    parts.append(
        "can trade (checked)"
        if check.get("can_trade")
        else "trading checked with the first tiny order"
    )
    if check.get("ip_locked"):
        parts.append("locked to listed addresses")
    elif check.get("ip_locked") is False:
        parts.append("NOT locked to an address")
    return "; ".join(parts)


def may_see(user: User, key: TradingKey) -> bool:
    perms = effective_permissions(user)
    if key.owner_id is None:
        return "live.keys.shared" in perms
    return key.owner_id == user.id


def may_use(user: User, key: TradingKey) -> bool:
    """Whose live bots may trade with this key (13c)."""
    perms = effective_permissions(user)
    if "live.trade" not in perms or not user.totp_enabled:
        return False
    return may_see(user, key)


def visible_keys(db: DbSession, user: User) -> list[TradingKey]:
    return [k for k in db.scalars(select(TradingKey).order_by(TradingKey.id)) if may_see(user, k)]
