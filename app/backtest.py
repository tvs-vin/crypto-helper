"""The backtester (12c): replay a plan over real past daily prices and compare it with simply
buying and holding the same coins with the same money.

Rules, so a backtest can't flatter a plan:
- **No looking ahead.** Each day's decision uses that day's closing price (and the days before);
  the order is filled at the *next* day's opening price.
- **Fees and slippage on every trade.** A buy pays `open x (1 + slippage)` per coin plus the fee
  on what it buys; a sale gets `open x (1 - slippage)` less the fee. The benchmark pays them too.
- **Money is Decimal** throughout; only the ratios shown (returns, drawdown) are rounded floats.

Plans:
- dca: buy a fixed amount on a schedule, split by weight (the starting money first);
- rebalance: hold target percentages (the rest in cash), rebalanced on a calendar or when a coin
  drifts more than N points; new money goes in by the targets;
- dip: keep the money in cash and buy a set amount whenever the coin is N % below its high of
  the last D days (once per drop: again after it recovers to half that drop);
- trend: hold the coin while it closes above its N-day average, cash below it.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import money
from app.models import DailyCandle
from app.prices.valuation import round_fiat

STRATEGIES = {
    "dca": "Regular buys (DCA)",
    "rebalance": "Rebalancing",
    "dip": "Buy the dip",
    "trend": "Trend (moving average)",
}
# Entry-tier taker fees (market orders), checked 2026-10-21. Coinbase's own page couldn't be
# read; reports differ (0.60 % or 0.90 % for US accounts): the higher one, to stay cautious.
FEES = {
    "coinbase": ("Coinbase Advanced", "0.9"),
    "kraken": ("Kraken Pro", "0.8"),
    "gemini": ("Gemini ActiveTrader", "1.2"),
    "binanceus": ("Binance.US", "0.02"),
}
MAX_YEARS = 30
MAX_TRADES_KEPT = 5000
SERIES_POINTS = 1500
Fiat = Literal["usd", "eur", "gbp", "jpy", "cad", "aud"]


def _dec(v, low: Decimal, high: Decimal, what: str) -> str:
    try:
        d = Decimal(str(v).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{what} must be a number") from None
    if not d.is_finite() or not low <= d <= high:
        raise ValueError(f"{what} must be between {low.normalize():f} and {high.normalize():f}")
    return format(d.normalize(), "f")


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["dca", "rebalance", "dip", "trend"]
    coins: dict[str, str] = Field(min_length=1, max_length=10)  # symbol -> percent
    start: date
    end: date
    currency: Fiat = "usd"
    initial: str = "1000"
    contribution: str = "0"
    every: Literal["none", "week", "month"] = "none"
    fee_pct: str = "0.9"
    slippage_pct: str = "0.1"
    rebalance: Literal["month", "quarter", "year", "threshold"] = "quarter"
    band: str = "5"  # threshold rebalancing: percentage points
    dip_pct: str = "20"
    dip_days: int = Field(default=30, ge=5, le=365)
    dip_amount: str = "100"
    ma_days: int = Field(default=50, ge=5, le=365)

    @model_validator(mode="after")
    def _check(self):
        clean = {}
        for sym, pct in self.coins.items():
            s = sym.strip().upper()
            if not s.isalnum() or len(s) > 10:
                raise ValueError(f"{sym!r} isn't a coin symbol")
            clean[s] = _dec(pct, Decimal("0.1"), Decimal(100), f"{s}'s share")
        total = sum(Decimal(v) for v in clean.values())
        if self.strategy == "dca" and total != 100:
            raise ValueError("The shares must add up to 100 %")
        if total > 100:
            raise ValueError("The shares add up to more than 100 %")
        if self.strategy in ("dip", "trend") and len(clean) != 1:
            raise ValueError("This plan works on one coin")
        self.coins = clean
        if self.end <= self.start + timedelta(days=7):
            raise ValueError("Pick at least a week between the dates")
        if (self.end - self.start).days > 366 * MAX_YEARS:
            raise ValueError(f"At most {MAX_YEARS} years")
        self.initial = _dec(self.initial, Decimal(0), Decimal("1e12"), "The starting money")
        self.contribution = _dec(self.contribution, Decimal(0), Decimal("1e12"), "Each addition")
        if Decimal(self.initial) == 0 and (self.every == "none" or Decimal(self.contribution) == 0):
            raise ValueError("Put some money in: starting money or regular additions")
        self.fee_pct = _dec(self.fee_pct, Decimal(0), Decimal(10), "The fee")
        self.slippage_pct = _dec(self.slippage_pct, Decimal(0), Decimal(10), "The slippage")
        self.band = _dec(self.band, Decimal(1), Decimal(50), "The band")
        self.dip_pct = _dec(self.dip_pct, Decimal(1), Decimal(90), "The drop")
        self.dip_amount = _dec(self.dip_amount, Decimal("0.01"), Decimal("1e12"), "The dip buy")
        return self


class NotEnoughData(ValueError):
    pass


# ---- prices --------------------------------------------------------------------------------


@dataclass
class Day:
    day: date
    open: dict[str, Decimal]
    close: dict[str, Decimal]
    high: dict[str, Decimal]


def warmup(p: Params) -> int:
    return p.ma_days if p.strategy == "trend" else p.dip_days if p.strategy == "dip" else 0


def load(db: DbSession, p: Params) -> tuple[list[Day], list[Day]]:
    """(days before the start for averages and highs, the days to simulate): only days every
    coin has a price for."""
    first = date.min if warmup(p) else p.start  # for the earliest possible start, if short
    rows: dict[str, dict[date, DailyCandle]] = {}
    for sym in p.coins:
        rows[sym] = {
            c.day: c
            for c in db.scalars(
                select(DailyCandle).where(
                    DailyCandle.symbol == sym,
                    DailyCandle.quote == p.currency,
                    DailyCandle.day >= first,
                    DailyCandle.day <= p.end,
                )
            )
        }
        if not rows[sym]:
            have = db.execute(
                select(func.min(DailyCandle.day), func.max(DailyCandle.day)).where(
                    DailyCandle.symbol == sym, DailyCandle.quote == p.currency
                )
            ).one()
            if have[0] is not None:
                raise NotEnoughData(
                    f"{sym} has daily {p.currency.upper()} prices from {have[0]} to {have[1]}: "
                    "pick dates in that range."
                )
            raise NotEnoughData(
                f"No daily {p.currency.upper()} prices for {sym}: import them in Settings → "
                "Prices → Past prices (if Coinbase trades it in that currency)."
            )
    common = sorted(set.intersection(*(set(r) for r in rows.values())))

    def at(d, k):
        return {s: Decimal(getattr(rows[s][d], k)) for s in p.coins}

    days = [Day(d, at(d, "open"), at(d, "close"), at(d, "high")) for d in common]
    before = [d for d in days if d.day < p.start][-warmup(p) :] if warmup(p) else []
    during = [d for d in days if d.day >= p.start]
    if len(during) < 8:
        firsts = ", ".join(f"{s} since {min(r)}" for s, r in rows.items())
        raise NotEnoughData(f"Not enough daily prices in that range ({firsts}).")
    if warmup(p) and len(before) < warmup(p):
        earliest = days[warmup(p)].day if len(days) > warmup(p) else None
        raise NotEnoughData(
            f"This plan needs {warmup(p)} days of prices before the start date"
            + (f": start on {earliest} or later." if earliest else ".")
        )
    return before, during


# ---- the simulation ------------------------------------------------------------------------


@dataclass
class Book:
    """One portfolio: cash, coins, and what its trades cost."""

    cash: Decimal = Decimal(0)
    units: dict[str, Decimal] = field(default_factory=dict)
    fees: Decimal = Decimal(0)
    slippage: Decimal = Decimal(0)
    trades: list[dict] = field(default_factory=list)
    keep_trades: bool = True

    def value(self, prices: dict[str, Decimal]) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = money.PRECISION
            return self.cash + sum((u * prices[s] for s, u in self.units.items()), Decimal(0))

    def buy(self, day: date, sym: str, spend: Decimal, open_: Decimal, fee: Decimal, slip: Decimal):
        spend = min(spend, self.cash)
        if spend <= 0:
            return
        with localcontext() as ctx:
            ctx.prec = money.PRECISION
            price = open_ * (1 + slip)
            notional = spend / (1 + fee)
            units = notional / price
            self.cash -= spend
            self.units[sym] = self.units.get(sym, Decimal(0)) + units
            self.fees += spend - notional
            self.slippage += units * (price - open_)
        self._log(day, "buy", sym, units, price, notional, spend - notional)

    def sell(
        self, day: date, sym: str, units: Decimal, open_: Decimal, fee: Decimal, slip: Decimal
    ):
        units = min(units, self.units.get(sym, Decimal(0)))
        if units <= 0:
            return
        with localcontext() as ctx:
            ctx.prec = money.PRECISION
            price = open_ * (1 - slip)
            gross = units * price
            cost = gross * fee
            self.units[sym] -= units
            self.cash += gross - cost
            self.fees += cost
            self.slippage += units * (open_ - price)
        self._log(day, "sell", sym, units, price, gross, cost)

    def _log(self, day, side, sym, units, price, value, fee):
        if self.keep_trades and len(self.trades) < MAX_TRADES_KEPT:
            q = Decimal("1e-8")
            self.trades.append(
                {
                    "day": day.isoformat(),
                    "side": side,
                    "symbol": sym,
                    "units": money.format_amount(units),
                    "price": money.format_amount(price.quantize(q)),
                    "value": money.format_amount(value.quantize(q)),
                    "fee": money.format_amount(fee.quantize(q)),
                }
            )


def contribution_days(days: list[Day], every: str) -> set[date]:
    """The days new money arrives (not the first: that's the starting money): weekly from the
    start, or monthly on the start's day of the month (or the month's last trading day)."""
    if every == "none" or not days:
        return set()
    start = days[0].day
    out: set[date] = set()
    if every == "week":
        return {d.day for d in days[1:] if (d.day - start).days % 7 == 0}
    seen = set()
    for d in days[1:]:
        key = (d.day.year, d.day.month)
        if key == (start.year, start.month) or key in seen:
            continue
        last = calendar.monthrange(d.day.year, d.day.month)[1]
        if d.day.day >= min(start.day, last):
            out.add(d.day)
            seen.add(key)
    return out


def new_period(prev: date, cur: date, kind: str) -> bool:
    if kind == "month":
        return (prev.year, prev.month) != (cur.year, cur.month)
    if kind == "quarter":
        return (prev.year, (prev.month - 1) // 3) != (cur.year, (cur.month - 1) // 3)
    return prev.year != cur.year


def simulate(p: Params, before: list[Day], days: list[Day]) -> dict:
    fee = Decimal(p.fee_pct) / 100
    slip = Decimal(p.slippage_pct) / 100
    weights = {s: Decimal(v) / 100 for s, v in p.coins.items()}
    invested_share = sum(weights.values())
    hold_weights = {s: w / invested_share for s, w in weights.items()}  # benchmark: all in
    plan, bench = Book(), Book(keep_trades=False)
    adds = contribution_days(days, p.every)
    contribution = Decimal(p.contribution)
    flows: list[tuple[date, Decimal]] = []
    pending: list[tuple[str, str, Decimal]] = []  # plan orders for the next open
    bench_pending: list[Decimal] = []  # benchmark cash to put in at the next open
    history = list(before)
    series = []
    armed = True  # buy the dip: one buy per drop
    in_market_days = 0
    twr, twr_bench, peak, peak_b, worst, worst_b = 1.0, 1.0, 1.0, 1.0, 0.0, 0.0
    prev_value = prev_bench = None

    for i, d in enumerate(days):
        # 1. Yesterday's decisions are filled at today's open (sales first: they free cash).
        for side, sym, amount in sorted(pending, key=lambda o: o[0] != "sell"):
            if side == "sell":
                plan.sell(d.day, sym, amount, d.open[sym], fee, slip)
            else:
                plan.buy(d.day, sym, amount, d.open[sym], fee, slip)
        pending = []
        for cash in bench_pending:
            for sym, w in hold_weights.items():
                bench.buy(d.day, sym, cash * w, d.open[sym], fee, slip)
        bench_pending = []

        # 2. New money arrives (the starting money on the first day).
        flow = Decimal(p.initial) if i == 0 else contribution if d.day in adds else Decimal(0)
        if flow:
            plan.cash += flow
            bench.cash += flow
            flows.append((d.day, flow))
            bench_pending.append(flow)

        # 3. Today's decision, on today's close, for tomorrow's open.
        history.append(d)
        close = d.close
        if p.strategy == "dca":
            if flow:
                pending += [("buy", s, flow * w) for s, w in weights.items()]
        elif p.strategy == "rebalance":
            total = plan.value(close)
            due = i == 0 or (
                p.rebalance != "threshold" and new_period(days[i - 1].day, d.day, p.rebalance)
            )
            if not due and p.rebalance == "threshold" and total > 0:
                due = any(
                    abs(plan.units.get(s, Decimal(0)) * close[s] / total - w) * 100
                    > Decimal(p.band)
                    for s, w in weights.items()
                )
            if due and total > 0:
                for s, w in weights.items():
                    diff = total * w - plan.units.get(s, Decimal(0)) * close[s]
                    if diff < 0:
                        pending.append(("sell", s, -diff / close[s]))
                    elif diff > 0:
                        pending.append(("buy", s, diff))
            elif flow:
                pending += [("buy", s, flow * w) for s, w in weights.items()]
        elif p.strategy == "dip":
            (sym,) = weights
            window = history[-p.dip_days :]
            high = max(x.high[sym] for x in window)
            drop = (high - close[sym]) * 100 / high
            if armed and drop >= Decimal(p.dip_pct) and plan.cash > 0:
                pending.append(("buy", sym, min(Decimal(p.dip_amount), plan.cash)))
                armed = False
            elif not armed and drop < Decimal(p.dip_pct) / 2:
                armed = True
        else:  # trend
            (sym,) = weights
            closes = [x.close[sym] for x in history[-p.ma_days :]]
            with localcontext() as ctx:
                ctx.prec = money.PRECISION
                ma = sum(closes, Decimal(0)) / len(closes)
            holding = plan.units.get(sym, Decimal(0)) > 0
            if close[sym] > ma:
                if plan.cash > 0:
                    pending.append(("buy", sym, plan.cash))
            elif holding:
                pending.append(("sell", sym, plan.units[sym]))
        if any(u > 0 for u in plan.units.values()):
            in_market_days += 1

        # 4. The day's value (at the close), and the time-weighted index for the worst drop.
        value, bvalue = plan.value(close), bench.value(close)
        if prev_value:
            twr *= float((value - flow) / prev_value) if prev_value else 1.0
        if prev_bench:
            twr_bench *= float((bvalue - flow) / prev_bench) if prev_bench else 1.0
        peak, peak_b = max(peak, twr), max(peak_b, twr_bench)
        worst = min(worst, twr / peak - 1)
        worst_b = min(worst_b, twr_bench / peak_b - 1)
        prev_value, prev_bench = value, bvalue
        series.append({"at": d.day.isoformat(), "value": round_fiat(value, p.currency),
                       "benchmark": round_fiat(bvalue, p.currency)})  # fmt: skip

    last = days[-1]
    put_in = sum((f for _, f in flows), Decimal(0))
    final, final_b = plan.value(last.close), bench.value(last.close)

    def summary(book: Book, end_value: Decimal, worst_drop: float) -> dict:
        profit = end_value - put_in
        return {
            "final": round_fiat(end_value, p.currency),
            "profit": round_fiat(profit, p.currency),
            "return_pct": round(float(profit / put_in * 100), 2) if put_in else None,
            "annual_pct": xirr(flows, last.day, end_value),
            "worst_drop_pct": round(worst_drop * 100, 2),
            "fees": round_fiat(book.fees, p.currency),
            "slippage": round_fiat(book.slippage, p.currency),
            "cash": round_fiat(book.cash, p.currency),
        }

    out = {
        "currency": p.currency,
        "first_day": days[0].day.isoformat(),
        "last_day": last.day.isoformat(),
        "days": len(days),
        "put_in": round_fiat(put_in, p.currency),
        "plan": {
            **summary(plan, final, worst),
            "trades": len(plan.trades),
            "in_market_pct": round(in_market_days * 100 / len(days), 1),
        },  # fmt: skip
        "buy_and_hold": summary(bench, final_b, worst_b),
    }
    return {"summary": out, "series": thin(series, SERIES_POINTS), "trades": plan.trades}


def xirr(flows: list[tuple[date, Decimal]], end: date, end_value: Decimal) -> float | None:
    """The yearly rate that turns the money put in (on its dates) into `end_value` on `end`,
    in percent (money-weighted, like a savings account's rate); None if it can't be found."""
    if not flows or end <= flows[0][0]:
        return None
    cash = [(-float(a), (end - d).days / 365.25) for d, a in flows] + [(float(end_value), 0.0)]

    def npv(r: float) -> float:
        return sum(a * (1 + r) ** t for a, t in cash)

    lo, hi = -0.9999, 100.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return round(((lo + hi) / 2) * 100, 2)


def thin(rows: list, most: int) -> list:
    if len(rows) <= most:
        return rows
    step = (len(rows) - 1) / (most - 1)
    return [rows[round(i * step)] for i in range(most)]


def run(db: DbSession, p: Params) -> dict:
    before, days = load(db, p)
    return simulate(p, before, days)


def describe(p: dict) -> str:
    coins = ", ".join(f"{s} {Decimal(v).normalize():f} %" for s, v in p["coins"].items())
    if p["strategy"] == "dca":
        what = f"DCA into {coins}"
    elif p["strategy"] == "rebalance":
        how = (
            f"when off by {p['band']} points"
            if p["rebalance"] == "threshold"
            else f"every {p['rebalance']}"
        )
        what = f"Rebalance {coins} {how}"
    elif p["strategy"] == "dip":
        sym = next(iter(p["coins"]))
        what = f"Buy {p['dip_amount']} of {sym} {p['dip_pct']} % below its {p['dip_days']}-day high"
    else:
        sym = next(iter(p["coins"]))
        what = f"Hold {sym} above its {p['ma_days']}-day average"
    return f"{what}, {p['start']} to {p['end']}"
