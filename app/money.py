"""Exact money amounts. Always Decimal, stored and sent as text, never float.

Floats can't represent most decimals (0.1 + 0.2 == 0.30000000000000004), and JSON numbers
are parsed into floats, so the API only accepts amounts as strings like "0.1".
"""

import re
from decimal import Decimal, localcontext

MAX_DECIMALS = 18
MAX_INTEGER_DIGITS = 18
# Plain digits with an optional fraction: no sign, exponent, spaces, commas, NaN or Infinity.
_AMOUNT_RE = re.compile(rf"^\d{{1,{MAX_INTEGER_DIGITS}}}(\.\d{{1,{MAX_DECIMALS}}})?$")
LIMIT = Decimal(10) ** MAX_INTEGER_DIGITS
# Enough precision for 18 integer + 18 fractional digits, with room to spare.
PRECISION = 60


class AmountError(ValueError):
    pass


def parse_amount(value, *, allow_zero: bool = True) -> Decimal:
    if not isinstance(value, str):
        raise AmountError('Send amounts as text, e.g. "0.1": JSON numbers lose precision.')
    text = value.strip()
    if not _AMOUNT_RE.match(text):
        raise AmountError(
            f"Amounts are plain numbers like 12 or 0.5, at most {MAX_INTEGER_DIGITS} digits "
            f"before the point and {MAX_DECIMALS} after, never negative."
        )
    amount = Decimal(text)
    if not allow_zero and amount == 0:
        raise AmountError("The amount must be more than zero.")
    return amount


def add(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        result = a + b
    if result >= LIMIT:
        raise AmountError("That would make a balance too large to track (10^18 or more).")
    return result


def subtract(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return a - b


def format_amount(amount: Decimal) -> str:
    """Canonical text: no exponent, no trailing zeros ("1.50" -> "1.5", "0E-18" -> "0")."""
    if amount == 0:
        return "0"
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
