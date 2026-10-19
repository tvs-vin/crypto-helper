"""The trade log as CSV for tax software (milestone 11d).

Each format follows the tool's own template, checked on 2026-10-19:
- TurboTax: Intuit's universal template (Custom_CSV_Template.csv) and help article
  ("Buy", "Sale", "Convert"; YYYY-MM-DD HH:mm:ss UTC; at most 8 decimals; no negatives).
- CoinLedger: its Universal Manual Import template sheet (MM/DD/YYYY HH:MM:SS UTC; "Trade").
- CoinTracker: its CoinTracker CSV format (MM/DD/YYYY HH:MM:SS; buys put the coin in
  Received and the currency paid in Sent).
- Koinly: its Universal format (YYYY-MM-DD HH:mm:ss UTC).
- Generic: our own, documented columns (every detail, exact amounts).

Times are UTC. Amounts are exact except TurboTax's (rounded to 8 decimals, as it requires).
"""

import csv
import io
from decimal import ROUND_HALF_EVEN, Decimal

from app.money import format_amount

FIAT = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "CHF"}
NAMES = {
    "coinbase": "Coinbase",
    "kraken": "Kraken",
    "gemini": "Gemini",
    "binanceus": "Binance.US",
    "demo": "Demo exchange",
}

FORMATS = {
    "generic": ("Generic CSV", "Every detail, exact amounts; for spreadsheets or any tool."),
    "koinly": ("Koinly", "Koinly's Universal format."),
    "cointracker": ("CoinTracker", "CoinTracker's CSV format."),
    "coinledger": ("CoinLedger", "CoinLedger's Universal Manual Import template."),
    "turbotax": (
        "TurboTax",
        "TurboTax's universal crypto template (amounts rounded to 8 "
        "decimals, as TurboTax requires).",
    ),
}

HEADERS = {
    "generic": [
        "time_utc",
        "exchange",
        "account",
        "side",
        "base",
        "quote",
        "amount",
        "price",
        "total",
        "fee",
        "fee_asset",
        "trade_id",
        "order_id",
    ],
    "koinly": [
        "Date",
        "Sent Amount",
        "Sent Currency",
        "Received Amount",
        "Received Currency",
        "Fee Amount",
        "Fee Currency",
        "Net Worth Amount",
        "Net Worth Currency",
        "Label",
        "Description",
        "TxHash",
    ],
    "cointracker": [
        "Date",
        "Received Quantity",
        "Received Currency",
        "Sent Quantity",
        "Sent Currency",
        "Fee Amount",
        "Fee Currency",
        "Tag",
    ],
    "coinledger": [
        "Date (UTC)",
        "Platform (Optional)",
        "Asset Sent",
        "Amount Sent",
        "Asset Received",
        "Amount Received",
        "Fee Currency (Optional)",
        "Fee Amount (Optional)",
        "Type",
        "Description (Optional)",
        "TxHash (Optional)",
    ],
    "turbotax": [
        "Date",
        "Type",
        "Sent Asset",
        "Sent Amount",
        "Received Asset",
        "Received Amount",
        "Fee Asset",
        "Fee Amount",
        "Market Value Currency",
        "Market Value",
        "Description",
        "Transaction Hash",
        "Transaction ID",
    ],
}


def text(value) -> str:
    """Plain text that a spreadsheet won't run as a formula (=, +, -, @ at the start)."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def eight(d: Decimal) -> str:
    return format_amount(d.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN))


def _sides(t):
    """(sent asset, sent amount, received asset, received amount) of one trade."""
    amount, total = Decimal(t.amount), Decimal(t.total)
    if t.side == "buy":
        return t.quote, total, t.base, amount
    return t.base, amount, t.quote, total


def _row(fmt: str, t) -> list[str]:
    sent_a, sent, recv_a, recv = _sides(t)
    fee, num = Decimal(t.fee), format_amount
    fee_txt, fee_asset = (num(fee), t.fee_asset) if fee else ("", "")
    iso = t.time.strftime("%Y-%m-%d %H:%M:%S")
    us = t.time.strftime("%m/%d/%Y %H:%M:%S")
    exchange = NAMES.get(t.exchange, t.exchange)
    note = text(f"{exchange} trade {t.trade_id}")
    if fmt == "generic":
        return [
            t.time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            exchange,
            text(t.account),
            t.side,
            t.base,
            t.quote,
            t.amount,
            t.price,
            t.total,
            t.fee,
            t.fee_asset,
            text(t.trade_id),
            text(t.order_id or ""),
        ]
    if fmt == "koinly":
        return [iso, num(sent), sent_a, num(recv), recv_a, fee_txt, fee_asset, "", "", "", note, ""]
    if fmt == "cointracker":
        return [us, num(recv), recv_a, num(sent), sent_a, fee_txt, fee_asset, ""]
    if fmt == "coinledger":
        return [
            us,
            exchange,
            sent_a,
            num(sent),
            recv_a,
            num(recv),
            fee_asset,
            fee_txt,
            "Trade",
            note,
            "",
        ]
    if fmt == "turbotax":
        fiat = t.quote in FIAT
        kind = ("Buy" if t.side == "buy" else "Sale") if fiat else "Convert"
        value_ccy = value = ""
        if fiat:  # what it cost (fee included) or what it brought in (fee taken off)
            fee_in_quote = fee if t.fee_asset == t.quote else Decimal(0)
            total = Decimal(t.total)
            value_ccy = t.quote
            value = eight(total + fee_in_quote if t.side == "buy" else total - fee_in_quote)
        return [
            iso,
            kind,
            sent_a,
            eight(sent),
            recv_a,
            eight(recv),
            fee_asset,
            eight(fee) if fee else "",
            value_ccy,
            value,
            note,
            "",
            text(t.trade_id),
        ]
    raise ValueError(f"unknown format {fmt}")


def render(fmt: str, trades) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt}")
    out = io.StringIO()
    w = csv.writer(out)  # standard CSV: quoted when needed, \r\n line ends
    w.writerow(HEADERS[fmt])
    for t in trades:
        w.writerow(_row(fmt, t))
    return out.getvalue()
