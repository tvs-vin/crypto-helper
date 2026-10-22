"""12b in a real browser: import past prices (from a local fake of Coinbase) in Settings, then
see them on Overview's price chart, years back."""

from datetime import timedelta

import pytest

from tests.test_daily_prices import TODAY, FakeCoinbase
from tests.ui.conftest import SCREENS, Server, _api, open_window, sign_in
from toolchain.tester.server import SpawnedServer


@pytest.fixture
def coinbase():
    fake = FakeCoinbase({"BTC": TODAY - timedelta(days=1500), "ETH": TODAY - timedelta(days=40)})
    yield fake
    fake.close()


@pytest.fixture
def importing_server(coinbase):
    s = SpawnedServer(extra_env={"BOT_DAILY_PRICES_URL": coinbase.url})
    s.start()
    _api(s, "POST", "/api/setup", {"token": s.setup_token, "password": s.password})
    yield Server(s)
    s.stop()


def test_import_past_prices_then_chart_them(importing_server, page):
    srv = importing_server
    sign_in(page, srv.base_url, "super", srv.password)
    page.click("[data-action=launcher]")
    page.click(".menu-item[data-panel=settings]")
    s = page.locator(".window[data-panel=settings]")
    s.locator("[data-section=prices]").click()
    s.locator("[data-action=start-import]").click()
    s.locator("text=Last import").wait_for(timeout=60000)
    btc = s.locator("tbody tr", has_text="BTC")
    assert f"USD {TODAY - timedelta(days=1500)}" in btc.inner_text()
    assert "h" in btc.inner_text()  # hourly ones too
    s.locator(".settings-block", has_text="Past prices").scroll_into_view_if_needed()
    page.screenshot(path=str(SCREENS / "past_prices_settings.png"))

    open_window(page, "overview")
    ov = page.locator(".window[data-panel=overview]")
    ov.locator("tr[data-symbol=BTC]").click()
    ov.locator(".coin-chart [aria-label=Range] button:has-text('All')").click()
    note = ov.locator(".chart-note")
    note.wait_for()
    assert "Coinbase's price history" in note.inner_text()
    page.screenshot(path=str(SCREENS / "past_prices_chart.png"))
