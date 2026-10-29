"""12a in a real browser: the Alerts window (each kind's form) and the Discord detail switches."""

from datetime import timedelta

from app.db import IMMEDIATE, make_engine, make_session_factory
from app.models import DailyCandle
from app.timeutil import utcnow
from tests.ui.conftest import SCREENS, open_window, sign_in


def seed_daily(server, symbol="BTC", days=60):
    engine = make_engine(f"sqlite:///{server.s.tmp.name}/tester.db")
    with make_session_factory(engine)() as db:
        db.connection(execution_options={IMMEDIATE: True})  # write lock first, like the app
        today = utcnow().date()
        for i in range(days, 0, -1):
            db.add(DailyCandle(symbol=symbol, day=today - timedelta(days=i), open="100",
                               high="110", low="90", close="100"))  # fmt: skip
        db.commit()
    engine.dispose()


def test_alerts_window(page, server):
    seed_daily(server)
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "alerts")
    win = page.locator(".window[data-panel=alerts]")
    win.locator(".empty, .table").first.wait_for()
    assert "Price alerts" in win.inner_text()  # the Overview ones are here too

    def new(kind_label):
        win.locator("[data-action=new-alert]").click()
        sheet = win.locator(".sheet")
        sheet.locator(f"[aria-label=Kind] button:has-text('{kind_label}')").click()
        return sheet

    sheet = new("Trend signal")
    assert "since" in sheet.inner_text()  # BTC has daily prices
    sol = sheet.locator("[name=symbol] option[value=SOL]")
    assert sol.get_attribute("disabled") is not None  # no daily prices for it
    sheet.locator("[name=days]").select_option("20")
    sheet.locator("[data-action=save-alert]").click()
    win.locator("tbody tr", has_text="BTC crosses its 20-day average").wait_for()

    sheet = new("Drift from targets")
    assert "60" == sheet.locator("[data-role=pct]").first.input_value()
    sheet.locator("[data-action=save-alert]").click()
    win.locator(
        "tbody tr", has_text="Drift of more than 5 points from BTC 60 %, ETH 40 %"
    ).wait_for()

    sheet = new("Portfolio value")
    sheet.locator("[name=condition]").select_option("move")
    sheet.locator("[name=value]").fill("10")
    sheet.locator("[name=window]").select_option("7d")
    sheet.locator("[data-action=save-alert]").click()
    win.locator("tbody tr", has_text="Portfolio moves 10 % or more in 7 days").wait_for()

    sheet = new("Drift from targets")
    sheet.locator("[data-role=pct]").first.fill("90")
    assert "more than 100" in sheet.inner_text()
    sheet.locator("[data-action=save-alert]").click()
    sheet.locator(".notice.error", has_text="more than 100").wait_for()  # the server says so too
    page.keyboard.press("Escape")  # still closes after a refused save (focus kept)
    sheet.wait_for(state="detached")
    page.screenshot(path=str(SCREENS / "alerts_window.png"))

    win.locator("tbody tr", has_text="Portfolio moves").locator(
        "[data-action=delete-alert]"
    ).click()
    gone = "() => !document.querySelector('.window[data-panel=alerts]').innerText"
    page.wait_for_function(gone + ".includes('Portfolio moves')")

    # Discord details: off by default, each one switchable.
    page.click("[data-action=launcher]")
    page.click(".menu-item[data-panel=settings]")
    s = page.locator(".window[data-panel=settings]")
    s.locator("[data-section=notifications]").click()
    boxes = s.locator("[data-detail]")
    boxes.first.wait_for()
    assert boxes.count() == 4 and not any(b.is_checked() for b in boxes.all())
    with page.expect_response(
        lambda r: r.url.endswith("/api/me/preferences") and r.request.method == "PATCH"
    ):
        s.locator("[data-detail=wallets]").check()
    s.locator("[data-detail=wallets]").scroll_into_view_if_needed()
    page.screenshot(path=str(SCREENS / "alerts_discord_details.png"))
    prefs = page.evaluate("() => fetch('/api/me/preferences').then((r) => r.json())")
    assert prefs["notifications"]["discord_details"] == ["wallets"]
