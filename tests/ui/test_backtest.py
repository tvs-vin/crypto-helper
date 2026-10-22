"""12c in a real browser: run plans in the Backtester, see them against buy and hold, save two
and compare them."""

import math
from datetime import timedelta

from app.db import make_engine, make_session_factory
from app.models import DailyCandle
from app.timeutil import utcnow
from tests.ui.conftest import SCREENS, open_window, sign_in


def seed(server, days=3 * 366):
    """Three years of made-up daily prices: BTC swings around a rising line, ETH flatter."""
    engine = make_engine(f"sqlite:///{server.s.tmp.name}/tester.db")
    today = utcnow().date()
    with make_session_factory(engine)() as db:
        for i in range(days):
            day = today - timedelta(days=days - i)
            for sym, base, amp in (("BTC", 20000 + i * 30, 0.25), ("ETH", 1500 + i, 0.15)):
                v = round(base * (1 + amp * math.sin(i / 40)), 2)
                hi, lo = str(round(v * 1.01, 2)), str(round(v * 0.99, 2))
                db.add(DailyCandle(symbol=sym, quote="usd", day=day, open=str(v), high=hi,
                                   low=lo, close=str(v)))  # fmt: skip
        db.commit()
    engine.dispose()


def test_backtester(page, server):
    seed(server)
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "backtest")
    w = page.locator(".window[data-panel=backtest]")
    w.locator("[data-action=run-backtest]").wait_for()

    # 1. Regular buys (the default): monthly into BTC, over 3 years.
    w.locator("[aria-label=Range] button:has-text('3y')").click()
    w.locator("[data-action=run-backtest]").click()
    w.locator(".bt-card", has_text="This plan").wait_for()
    assert w.locator(".bt-card").count() == 2
    assert w.locator("svg.chart path.line.other").count() == 1  # buy and hold, dashed
    w.locator("[name=run_name]").fill("Monthly BTC")
    w.locator("[data-action=save-backtest]").click()
    w.locator("tbody tr", has_text="Monthly BTC").wait_for()

    # 2. Rebalancing 60/40 BTC/ETH.
    w.locator("[aria-label=Plan] button:has-text('Rebalancing')").click()
    w.locator("button:has-text('+ Coin')").click()
    pcts = w.locator("[data-role=pct]")
    pcts.nth(0).fill("60")
    pcts.nth(1).fill("40")
    w.locator("[data-action=run-backtest]").click()
    w.locator(".bt-result h3", has_text="Rebalance BTC 60 %, ETH 40 % every quarter").wait_for()
    page.wait_for_timeout(500)  # the window scrolls to the results
    page.screenshot(path=str(SCREENS / "backtest_result.png"))
    w.locator("[name=run_name]").fill("60/40 quarterly")
    w.locator("[data-action=save-backtest]").click()
    w.locator("tbody tr", has_text="60/40 quarterly").wait_for()

    # 3. A plan that needs history before its start: a clear refusal.
    w.locator("[aria-label=Plan] button:has-text('Trend')").click()
    w.locator("[aria-label=Range] button:has-text('Max')").click()
    w.locator("[name=ma_days]").select_option("200")
    w.locator("[data-action=run-backtest]").click()
    w.locator(
        ".bt-result .notice.error", has_text="days of prices before the start date"
    ).wait_for()

    # 4. Compare the two saved runs.
    for name in ("Monthly BTC", "60/40 quarterly"):
        w.locator("tbody tr", has_text=name).locator("input[type=checkbox]").check()
    w.locator("[data-action=compare-runs]").click()
    cmp = w.locator(".bt-compare")
    cmp.wait_for()
    text = cmp.inner_text().lower()
    assert "monthly btc" in text and "60/40 quarterly" in text and "worst drop" in text
    cmp.scroll_into_view_if_needed()
    page.screenshot(path=str(SCREENS / "backtest_compare.png"))
