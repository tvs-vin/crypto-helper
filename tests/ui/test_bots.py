"""12d in a real browser: make a paper bot, see it fill against buy and hold, start one from a
Backtester run, trip the kill switch and re-arm it."""

import math
from datetime import timedelta

from app.bots import BotJob
from app.config import Settings
from app.db import make_engine, make_session_factory
from app.models import DailyCandle
from app.prices.providers import make_provider
from app.prices.service import PriceService
from app.timeutil import utcnow
from tests.ui.conftest import SCREENS, open_window, sign_in


def seed(server, days=400):
    """A year of made-up daily prices up to yesterday (the bots' first decision day)."""
    engine = make_engine(f"sqlite:///{server.s.tmp.name}/tester.db")
    today = utcnow().date()
    with make_session_factory(engine)() as db:
        for i in range(days):
            day = today - timedelta(days=days - i)
            for sym, base in (("BTC", 60000 + i * 20), ("ETH", 3000 + i)):
                v = round(base * (1 + 0.2 * math.sin(i / 30)), 2)
                db.add(DailyCandle(symbol=sym, quote="usd", day=day, open=str(v), high=str(v),
                                   low=str(v), close=str(v)))  # fmt: skip
        db.commit()
    engine.dispose()


def checker(server):
    """The bots' minute check, run here against the server's database (the UI test server has
    no background jobs). Mock prices, like the server's."""
    engine = make_engine(f"sqlite:///{server.s.tmp.name}/tester.db")
    prices = PriceService(make_provider(Settings(price_provider="mock")), 60)
    return engine, BotJob(prices, make_session_factory(engine))


def test_paper_trading(page, server):
    seed(server)
    engine, job = checker(server)
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "bots")
    w = page.locator(".window[data-panel=bots]")
    w.locator(".empty", has_text="No bots yet").wait_for()
    assert w.locator("[data-kill=armed]").count() == 1

    # 1. A new bot: regular buys into BTC, with a largest order smaller than its first buy.
    w.locator("[data-action=new-bot]").click()
    sheet = page.locator(".sheet")
    sheet.locator("[name=bot_name]").fill("Weekly BTC")
    sheet.locator("[name=every]").select_option("week")
    sheet.locator("[name=max_order]").fill("600")
    page.screenshot(path=str(SCREENS / "bots_new.png"))
    sheet.locator("[data-action=create-bot]").click()
    w.locator("h3", has_text="Weekly BTC").wait_for()
    w.locator("td", has_text="pending").wait_for()  # decided on yesterday's close, not filled yet

    now = utcnow()
    assert job.tick(now)["filled"] == 1
    assert job.tick(now + timedelta(hours=1)) == {"filled": 0, "decided": 0}  # an hourly point
    w.locator("[data-action=all-bots]").click()
    card = w.locator(".bot-card", has_text="Weekly BTC")
    card.locator(".big").wait_for()
    assert "Buy and hold" in card.inner_text()

    # 2. From the Backtester: run a tested plan on paper.
    open_window(page, "backtest")
    bt = page.locator(".window[data-panel=backtest]")
    bt.locator("[aria-label=Plan] button:has-text('Rebalancing')").click()
    bt.locator("button:has-text('+ Coin')").click()
    pcts = bt.locator("[data-role=pct]")
    pcts.nth(0).fill("60")
    pcts.nth(1).fill("40")
    bt.locator("[aria-label=Range] button:has-text('1y')").click()
    bt.locator("[data-action=run-backtest]").click()
    bt.locator(".bt-card", has_text="This plan").wait_for()
    bt.locator("[data-action=paper-trade]").click()
    page.locator(".sheet [name=bot_name]").fill("60/40 on paper")
    page.locator(".sheet [data-action=create-bot]").click()
    w.locator(".bot-card", has_text="60/40 on paper").wait_for()  # the window is told live
    job.tick(now + timedelta(minutes=2))
    job.tick(now + timedelta(hours=2))
    page.locator(".window[data-panel=backtest] .win-btn.close").click()

    # 3. Its detail: both lines, the orders, the limit that cut the first one.
    w.locator(".bot-card", has_text="Weekly BTC").locator("[data-action=open-bot]").click()
    w.locator("svg.chart path.line.other").wait_for(state="attached")  # flat: mock prices
    w.locator("td", has_text="cut to the largest order").wait_for()
    page.screenshot(path=str(SCREENS / "bots_detail.png"))
    w.locator("td", has_text="cut to the largest order").scroll_into_view_if_needed()
    page.screenshot(path=str(SCREENS / "bots_orders.png"))
    w.locator("[data-action=all-bots]").click()
    w.locator(".bot-card", has_text="60/40 on paper").locator(".big").wait_for()
    page.screenshot(path=str(SCREENS / "bots_list.png"))

    # 4. The kill switch: everything stops, nothing starts until it's re-armed.
    w.locator("[data-action=kill]").click()
    page.locator(".sheet [name=reason]").fill("kill switch drill")
    page.locator(".sheet [data-action=confirm-kill]").click()
    w.locator("[data-kill=tripped]", has_text="kill switch drill").wait_for()
    w.locator(".bot-card .badge.warn", has_text="paused").nth(1).wait_for()
    assert w.locator("[data-action=start-bot]").first.is_disabled()
    assert job.tick(now + timedelta(hours=3)) == {"skipped": "the kill switch is tripped"}
    page.screenshot(path=str(SCREENS / "bots_killed.png"))

    w.locator("[data-action=rearm]").click()
    typed = page.locator(".sheet [name=confirm]")
    typed.fill("rearm")
    assert page.locator(".sheet [data-action=confirm-rearm]").is_disabled()
    typed.fill("REARM")
    page.locator(".sheet [data-action=confirm-rearm]").click()
    w.locator("[data-kill=armed]", has_text="Last tripped").wait_for()
    w.locator(".bot-card", has_text="Weekly BTC").locator("[data-action=start-bot]").click()
    w.locator(".bot-card", has_text="Weekly BTC").locator(
        ".badge.ok", has_text="running"
    ).wait_for()
    engine.dispose()
