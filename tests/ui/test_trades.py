"""11d in a real browser: the Trade log window, filters, and a CSV download."""

import csv
import io

from tests.ui.conftest import open_window, sign_in


def test_trade_log_and_download(page, server):
    cookie = server.admin_cookie()
    _, _, conn = server.api(
        "POST",
        "/api/connections",
        {
            "kind": "demo",
            "label": "Practice",
            "credentials": {"key": "demo-key-trades-1", "secret": "s"},
        },
        cookie,
    )
    _, _, w = server.api(
        "POST", "/api/wallets", {"name": "Trading account", "kind": "exchange"}, cookie
    )
    server.api(
        "PUT",
        f"/api/wallets/{w['id']}/source",
        {"kind": "exchange", "connection_id": conn["id"]},
        cookie,
    )
    server.api("POST", f"/api/wallets/{w['id']}/sync", {}, cookie)

    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "trades")
    t = page.locator(".window[data-panel=trades]")
    t.locator("tbody tr").first.wait_for()
    assert t.locator("tbody tr").count() == 3 and "3 trades" in t.inner_text()
    t.locator("[name=trade_asset]").fill("eth")
    page.wait_for_function(
        "() => document.querySelectorAll('.window[data-panel=trades] tbody tr').length === 2"
    )
    assert "2026-03-15 09:45" in t.inner_text()  # UTC, as in the tax files
    page.screenshot(path="tests/ui/screens/trade_log.png")
    t.locator("[name=trade_format]").select_option("turbotax")
    with page.expect_download() as dl:
        t.locator("[data-action=export-trades]").click()
    download = dl.value
    assert download.suggested_filename.startswith("trades-turbotax-")
    rows = list(csv.reader(io.StringIO(open(download.path(), encoding="utf-8").read())))
    assert rows[0][:2] == ["Date", "Type"] and len(rows) == 3  # filtered to ETH: 2 trades
    assert {r[1] for r in rows[1:]} == {"Buy", "Sale"}
