"""11e in a real browser: the portfolio over time (Overview), and a wallet's trend and history
(Wallets)."""

from datetime import timedelta

from app.db import make_engine, make_session_factory
from app.models import BalancePoint, BalanceSnapshot
from app.timeutil import utcnow
from tests.ui.conftest import open_window, sign_in


def seed_history(server, wallets):
    """30 days of daily snapshots, straight into the throwaway server's database: the value
    climbs from 1000 to 1290 (Savings) and 500 to 645 (Trading); the coin amounts double on
    day 20."""
    engine = make_engine(f"sqlite:///{server.s.tmp.name}/tester.db")
    factory = make_session_factory(engine)
    now = utcnow().replace(microsecond=0)
    with factory() as db:
        for day in range(30, 0, -1):
            shot = BalanceSnapshot(at=now - timedelta(days=day, hours=-1), daily=True)
            db.add(shot)
            db.flush()
            step = 30 - day
            for (wid, symbol, base), amount in zip(wallets, ("0.01", "0.2"), strict=True):
                usd = base + step * base // 100
                db.add(
                    BalancePoint(
                        snapshot_id=shot.id,
                        wallet_id=wid,
                        symbol=symbol,
                        amount=amount if step < 20 else str(2 * float(amount)),
                        values={"usd": f"{usd}.00"},
                    )
                )
        db.commit()
    engine.dispose()


def test_portfolio_and_wallet_history(page, server):
    cookie = server.admin_cookie()
    made = []
    for name, symbol, amount in (("Savings", "BTC", "0.02"), ("Trading", "ETH", "0.4")):
        _, _, w = server.api("POST", "/api/wallets", {"name": name, "kind": "paper"}, cookie)
        server.api("PUT", f"/api/wallets/{w['id']}/holdings/{symbol}", {"amount": amount}, cookie)
        made.append(w["id"])
    # Wallets made "now" only count from now: date them back so the seeded month shows.
    engine = make_engine(f"sqlite:///{server.s.tmp.name}/tester.db")
    with engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(
            text("UPDATE wallets SET created_at = :t"), {"t": utcnow() - timedelta(days=40)}
        )
    engine.dispose()
    seed_history(server, [(made[0], "BTC", 1000), (made[1], "ETH", 500)])

    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "overview")
    ov = page.locator(".window[data-panel=overview]")
    chart = ov.locator(".folio-history svg[aria-label='Portfolio value over time']")
    chart.wait_for()
    head = ov.locator(".folio-history .chart-head").inner_text()
    assert "Portfolio over time" in head
    assert "+$435.00 (+29.00%)" in head  # 1500 -> 1935 over the month (exact, from the server)
    ov.locator(".folio-history [data-value='7']").click()
    page.wait_for_function(
        "() => document.querySelector('.window[data-panel=overview] .folio-history .chart-head')"
        "?.innerText.includes('+$90.00')"
    )  # the last 7 days: 1845 -> 1935
    ov.locator(".folio-history [data-value='30']").click()
    page.wait_for_function(
        "() => document.querySelector('.window[data-panel=overview] .folio-history .chart-head')"
        "?.innerText.includes('+$435.00')"
    )
    page.screenshot(path="tests/ui/screens/portfolio_history.png")

    open_window(page, "wallets")
    wl = page.locator(".window[data-panel=wallets]")
    card = wl.locator(".wallet-card", has_text="Savings")
    card.locator(".trend svg.spark path.line.up").wait_for()  # the 30-day trend, going up
    card.locator("[data-action=wallet-history]").click()
    sheet = wl.locator(".sheet")
    sheet.locator("svg[aria-label='Savings: value over time']").wait_for()
    text = sheet.inner_text()
    assert "Savings: history" in text and "+$290.00 (+29.00%)" in text
    # How the coins changed: 0.01 BTC at the start, 0.02 at the end.
    rows = sheet.locator("tbody tr")
    assert rows.count() == 1
    cells = rows.first.locator("td").all_inner_texts()
    assert cells[0] == "BTC" and cells[1] == "0.01" and cells[2] == "0.02"
    # Everything fits inside the sheet (nothing sticks out on the right).
    fits = page.evaluate(
        """() => { const s = document.querySelector('.window[data-panel=wallets] .sheet');
        const r = s.getBoundingClientRect();
        return [...s.querySelectorAll('.chart-head, svg.chart, table')]
          .every((e) => e.getBoundingClientRect().right <= r.right + 0.5); }"""
    )
    assert fits
    page.screenshot(path="tests/ui/screens/wallet_history.png")
    sheet.locator("[data-value='7']").click()
    page.wait_for_function(
        "() => document.querySelector('.window[data-panel=wallets] .sheet')"
        "?.innerText.includes('+$60.00')"
    )
    page.keyboard.press("Escape")  # still closes after picking a range (focus kept)
    sheet.wait_for(state="detached")
    page.screenshot(path="tests/ui/screens/wallet_trends.png")

    # A new wallet with no history yet still has a way in, and says what's coming.
    server.api("POST", "/api/wallets", {"name": "Brand new", "kind": "paper"}, cookie)
    wl.locator("select[aria-label=Sort]").select_option("name")  # reloads the cards
    fresh = wl.locator(".wallet-card", has_text="Brand new")
    assert fresh.locator(".trend").inner_text() == "History"
    fresh.locator("[data-action=wallet-history]").click()
    wl.locator(".sheet", has_text="No history for this range yet").wait_for()
