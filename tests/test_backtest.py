"""12c: the backtester. Exact fee and slippage maths, no looking ahead, each plan's rules, the
benchmark, the yearly rate and the worst drop; then the API (run, save, compare, CSV) and its
rules."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import backtest as bt
from app.models import DailyCandle
from tests.conftest import H
from tests.wallet_helpers import user_with

START = date(2024, 1, 1)


def days(prices, coin="BTC", opens=None, highs=None, start=START):
    """Day objects from closing prices (open = close unless given)."""
    out = []
    for i, c in enumerate(prices):
        c = Decimal(str(c))
        o = Decimal(str(opens[i])) if opens else c
        hi = Decimal(str(highs[i])) if highs else max(o, c)
        out.append(bt.Day(start + timedelta(days=i), {coin: o}, {coin: c}, {coin: hi}))
    return out


def params(**kw):
    base = dict(strategy="dca", coins={"BTC": "100"}, start=START, end=START + timedelta(days=60),
                initial="1000", fee_pct="0", slippage_pct="0")  # fmt: skip
    return bt.Params(**{**base, **kw})


# ---- the maths -------------------------------------------------------------------------------


def test_a_buy_pays_slippage_and_fee_at_the_next_open():
    d = days([10] * 10, opens=[10, 20] + [20] * 8)  # day 2 opens at 20
    r = bt.simulate(params(fee_pct="1", slippage_pct="1"), [], d)
    (t,) = r["trades"]
    assert t["day"] == str(START + timedelta(days=1))  # decided on day 1's close, filled next open
    assert Decimal(t["price"]) == Decimal("20.2")  # 20 x (1 + 1 %)
    notional = Decimal(1000) / Decimal("1.01")
    assert Decimal(t["value"]) == notional.quantize(Decimal("1e-8"))
    assert Decimal(t["fee"]) == (Decimal(1000) - notional).quantize(Decimal("1e-8"))
    plan = r["summary"]["plan"]
    assert plan["fees"] == "9.90" and plan["cash"] == "0.00"
    # Its units are worth 10 each at the close: 1000/1.01/20.2 units x 10.
    assert plan["final"] == bt.round_fiat(notional / Decimal("20.2") * 10, "usd")


def test_dca_into_one_coin_is_buy_and_hold():
    d = days([10, 12, 8, 9, 15, 7, 11] * 9)
    r = bt.simulate(
        params(contribution="50", every="week", fee_pct="0.5", slippage_pct="0.2"), [], d
    )
    s = r["summary"]
    assert s["plan"]["final"] == s["buy_and_hold"]["final"]
    assert s["put_in"] == str(1000 + 50 * 8) + ".00"  # weeks 1-8 after the start


def test_worst_drop_ignores_new_money():
    # 100 -> 50 -> 100: a 50 % drop, whatever is added meanwhile.
    d = days([100, 100, 75, 50, 75, 100, 100, 100, 100, 100])
    r = bt.simulate(params(contribution="10000", every="week"), [], d)
    assert r["summary"]["plan"]["worst_drop_pct"] == -50.0


def test_new_money_mid_fall_doesnt_hide_the_drop():
    # 100 -> 75, money added while it's at 75, then on down to 50: still a 50 % drop.
    d = days([100] * 5 + [75] * 5 + [50] * 5)
    r = bt.simulate(params(contribution="10000", every="week"), [], d)
    assert r["summary"]["plan"]["worst_drop_pct"] == -50.0


def test_a_buy_never_spends_more_than_the_cash():
    book = bt.Book(cash=Decimal(100))
    book.buy(START, "BTC", Decimal(500), Decimal(10), Decimal(0), Decimal(0))
    assert book.cash == 0 and book.units["BTC"] == 10
    # Rebalancing plans buys on the close; if the sales fetch less at the next open, the buys
    # shrink to the cash there is.
    d = two_coins([100] * 10 + [200] * 20 + [100] * 30, [100] * 60)
    gap = [bt.Day(x.day, {"BTC": x.open["BTC"] * Decimal("0.8"), "ETH": x.open["ETH"]}, x.close,
                  x.high) for x in d]  # opens 20 % below the close  # fmt: skip
    r = bt.simulate(params(strategy="rebalance", coins={"BTC": "50", "ETH": "50"},
                           rebalance="month", end=START + timedelta(days=70)), [], gap)  # fmt: skip
    assert Decimal(r["summary"]["plan"]["cash"]) >= 0


def test_yearly_rate():
    flows = [(date(2020, 1, 1), Decimal(100))]
    rate = bt.xirr(flows, date(2022, 1, 1), Decimal(121))  # two years (731 days): about 10 %
    assert abs(rate - 10.0) < 0.05
    assert bt.xirr(flows, date(2020, 1, 1), Decimal(100)) is None


def test_contribution_days():
    d = days([1] * 70, start=date(2024, 1, 31))
    monthly = sorted(bt.contribution_days(d, "month"))
    assert monthly == [date(2024, 2, 29), date(2024, 3, 31)]  # the month's last when it's short
    weekly = sorted(bt.contribution_days(d, "week"))
    assert weekly[0] == date(2024, 2, 7) and len(weekly) == 9
    assert bt.contribution_days(d, "none") == set()


# ---- the plans -------------------------------------------------------------------------------


def two_coins(btc, eth):
    return [
        bt.Day(START + timedelta(days=i), {"BTC": Decimal(b), "ETH": Decimal(e)},
               {"BTC": Decimal(b), "ETH": Decimal(e)}, {"BTC": Decimal(b), "ETH": Decimal(e)})
        for i, (b, e) in enumerate(zip(btc, eth, strict=True))
    ]  # fmt: skip


def test_rebalancing_on_a_calendar():
    # BTC doubles in January; at February's first day the plan sells BTC and buys ETH.
    n = 45
    btc = [100 + i * 100 / 30 if i <= 30 else 200 for i in range(n)]
    d = two_coins(btc, [100] * n)
    p = params(strategy="rebalance", coins={"BTC": "50", "ETH": "50"}, rebalance="month")
    r = bt.simulate(p, [], d)
    sides = [(t["day"], t["side"], t["symbol"]) for t in r["trades"]]
    assert sides[:2] == [(str(START + timedelta(days=1)), "buy", "BTC"),
                         (str(START + timedelta(days=1)), "buy", "ETH")]  # fmt: skip
    feb = str(date(2024, 2, 2))  # decided on Feb 1's close, filled Feb 2
    assert (feb, "sell", "BTC") in sides and (feb, "buy", "ETH") in sides
    assert Decimal(r["summary"]["plan"]["final"]) > 0


def test_rebalancing_by_threshold_and_cash():
    btc = [100] * 5 + [130] * 10
    d = two_coins(btc, [100] * 15)
    p = params(strategy="rebalance", coins={"BTC": "40", "ETH": "40"}, rebalance="threshold",
               band="5")  # 20 % stays in cash  # fmt: skip
    r = bt.simulate(p, [], d)
    assert any(t["side"] == "sell" and t["symbol"] == "BTC" for t in r["trades"])
    assert Decimal(r["summary"]["plan"]["cash"]) > 0  # the cash share stays cash


def test_buy_the_dip_once_per_drop():
    # High 100; falls to 70 (30 % drop: buy once), stays low (no more), recovers, falls again.
    closes = [100] * 5 + [70] * 5 + [100] * 5 + [70] * 5
    p = params(strategy="dip", dip_pct="25", dip_days=5, dip_amount="300")
    r = bt.simulate(p, days([100] * 5), days(closes))
    buys = [t for t in r["trades"] if t["side"] == "buy"]
    assert len(buys) == 2 and all(Decimal(t["value"]) == 300 for t in buys)
    assert r["summary"]["plan"]["cash"] == "400.00"  # 1000 - 2 x 300 waits for dips


def test_trend_holds_above_the_average_only():
    closes = [10] * 5 + [20] * 5 + [5] * 5
    p = params(strategy="trend", ma_days=5)
    r = bt.simulate(p, days([10] * 5), days(closes))
    sides = [t["side"] for t in r["trades"]]
    assert sides == ["buy", "sell"]  # in when it rose above, out when it fell below
    assert 0 < r["summary"]["plan"]["in_market_pct"] < 100


# ---- settings --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"coins": {"BTC": "60"}}, "add up to 100"),
        ({"strategy": "dip", "coins": {"BTC": "50", "ETH": "50"}}, "one coin"),
        ({"strategy": "rebalance", "coins": {"BTC": "70", "ETH": "40"}}, "more than 100"),
        ({"end": START + timedelta(days=3)}, "at least a week"),
        ({"end": START + timedelta(days=366 * 31)}, "At most 30 years"),
        ({"initial": "0"}, "Put some money in"),
        ({"fee_pct": "50"}, "The fee must be between"),
        ({"coins": {"B-T": "100"}}, "isn't a coin symbol"),
    ],
)
def test_bad_settings(kw, message):
    with pytest.raises(ValueError, match=message):
        params(**kw)


# ---- the API ---------------------------------------------------------------------------------


def seed(app, symbol="BTC", n=400, quote="usd", start=date(2023, 1, 1)):
    with app.state.session_factory() as db:
        for i in range(n):
            v = str(100 + (i % 50))
            db.add(DailyCandle(symbol=symbol, quote=quote, day=start + timedelta(days=i), open=v,
                               high=v, low=v, close=v))  # fmt: skip
        db.commit()


P = {"strategy": "dca", "coins": {"BTC": "100"}, "start": "2023-03-01", "end": "2023-12-31",
     "initial": "1000", "contribution": "100", "every": "month"}  # fmt: skip


def test_run_save_compare_and_csv(logged_in, app):
    seed(app)
    meta = logged_in.get("/api/backtests/meta").json()
    assert meta["coverage"]["BTC"]["usd"]["days"] == 400 and "kraken" in meta["fees"]
    r = logged_in.post("/api/backtests/run", json={"params": P}, headers=H).json()
    assert r["summary"]["put_in"] == "1900.00" and r["text"].startswith("DCA into BTC 100 %")
    assert logged_in.get("/api/backtests").json()["runs"] == []  # running saves nothing
    s = logged_in.post("/api/backtests", json={"name": "=monthly", "params": P}, headers=H)
    assert s.status_code == 201
    rid = s.json()["id"]
    full = logged_in.get(f"/api/backtests/{rid}").json()
    assert full["summary"] == r["summary"] and full["trades_total"] == 10
    csv = logged_in.get(f"/api/backtests/{rid}/trades.csv")
    lines = csv.text.strip().splitlines()
    assert lines[0] == "day,side,symbol,units,price,value,fee,currency" and len(lines) == 11
    assert 'filename="backtest--monthly.csv"' in csv.headers["content-disposition"]
    actions = [e["action"] for e in logged_in.get("/api/audit?q=backtest").json()]
    assert actions == ["backtest.save"]
    assert logged_in.delete(f"/api/backtests/{rid}", headers=H).status_code == 204
    assert logged_in.get(f"/api/backtests/{rid}").status_code == 404


def test_api_refusals(logged_in, app):
    seed(app)
    bad = {**P, "coins": {"ETH": "100"}}
    r = logged_in.post("/api/backtests/run", json={"params": bad}, headers=H)
    assert r.status_code == 422 and "No daily USD prices for ETH" in r.json()["detail"]
    early = {**P, "start": "2022-01-01", "end": "2022-03-01"}
    r = logged_in.post("/api/backtests/run", json={"params": early}, headers=H)
    assert r.status_code == 422
    assert r.json()["detail"] == (
        "BTC has daily USD prices from 2023-01-01 to 2024-02-04: pick dates in that range."
    )
    r = logged_in.post("/api/backtests/run", json={"params": {**P, "coins": {"BTC": "50"}}},
                       headers=H)  # fmt: skip
    assert r.status_code == 422 and "add up to 100" in r.json()["detail"]
    seedphrase = " ".join(["zoo"] * 11 + ["wrong"])  # a valid 12-word phrase, short enough
    r = logged_in.post("/api/backtests", json={"name": seedphrase, "params": P}, headers=H)
    assert r.status_code == 422 and "abandon" not in r.text


def test_only_your_own_and_permissions(logged_in, app, monkeypatch):
    from app.routers import backtests as router

    seed(app)
    rid = logged_in.post("/api/backtests", json={"name": "mine", "params": P}, headers=H).json()[
        "id"
    ]
    viewer = user_with(app, logged_in, "viewer", ["prices.view"])
    assert viewer.get("/api/backtests").json()["runs"] == []
    assert viewer.get(f"/api/backtests/{rid}").status_code == 404
    assert viewer.delete(f"/api/backtests/{rid}", headers=H).status_code == 404
    nobody = user_with(app, logged_in, "nobody", ["wallets.view"])
    assert nobody.post("/api/backtests/run", json={"params": P}, headers=H).status_code == 403
    monkeypatch.setattr(router, "MAX_SAVED", 1)
    r = logged_in.post("/api/backtests", json={"name": "two", "params": P}, headers=H)
    assert r.status_code == 409


def test_a_sale_gets_the_next_open_less_slippage_and_fee():
    """Phase 3 review: sales had no test of their price (only buys did)."""
    before = days([100] * 20, start=START - timedelta(days=20))
    # Day 0 closes above the 20-day average (buy at day 1's open); day 2 closes far below it
    # (sell at day 3's open, 80, not day 2's close, 50).
    d = days([110, 110, 50] + [60] * 8, opens=[110, 110, 110, 80] + [60] * 7)
    r = bt.simulate(params(strategy="trend", ma_days=20, fee_pct="1", slippage_pct="1",
                           end=START + timedelta(days=10)), before, d)  # fmt: skip
    sale = next(t for t in r["trades"] if t["side"] == "sell")
    assert sale["day"] == str(START + timedelta(days=3))
    assert Decimal(sale["price"]) == Decimal("79.2")  # 80 x (1 - 1 %)
    assert Decimal(sale["fee"]) == (Decimal(sale["value"]) * Decimal("0.01")).quantize(
        Decimal("1e-8")
    )


def test_a_plan_needs_its_history_before_the_start(logged_in, app):
    seed(app)  # prices from 2023-01-01
    trend = {**P, "strategy": "trend", "ma_days": 200, "every": "none", "contribution": "0"}
    r = logged_in.post("/api/backtests/run", json={"params": trend}, headers=H)
    assert r.status_code == 422 and "200 days of prices before the start date" in r.json()["detail"]
