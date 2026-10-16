"""The data windows (6b) in a real browser, against seeded data."""

import time

import pytest

from tests.ui.conftest import open_window, sign_in
from tests.ui.seed import SEED_PHRASE_FREE, seed


@pytest.fixture(scope="module")
def seeded(server):
    cookie, wallets = seed(server.s)
    return wallets


@pytest.fixture
def super_page(page, server, seeded):
    sign_in(page, server.base_url, "super", server.password)
    page.evaluate("document.querySelector('.toasts')?.remove()")
    return page


def card(pg, text):
    return pg.locator(".wallet-card", has_text=text)


def wallet_action(pg, nickname, action):
    card(pg, nickname).locator("[data-action=wallet-menu]").click()
    pg.click(f".menu [data-action={action}]")


def no_null_text(pg):
    assert "null" not in pg.inner_text("#desktop").lower().split()
    assert "undefined" not in pg.inner_text("#desktop")


# ---- wallets -----------------------------------------------------------------------------


def test_wallet_cards_show_nickname_name_tags_and_values(super_page):
    pg = super_page
    open_window(pg, "wallets")
    c = card(pg, "Cold storage")
    c.wait_for()
    assert c.locator(".nick").inner_text().strip() == "Cold storage"
    assert c.locator(".name").inner_text() == "Ledger BTC"
    assert "long-term" in c.locator(".chip:not(.system)").all_inner_texts()
    assert "network:bitcoin" in c.locator(".chip.system").all_inner_texts()
    assert c.locator("footer strong").inner_text().startswith("$")
    band = c.locator(".band").evaluate("e => getComputedStyle(e).backgroundImage")
    assert "linear-gradient" in band
    no_null_text(pg)


def test_create_wallet_with_everything(super_page):
    pg = super_page
    open_window(pg, "wallets")
    pg.click("[data-action=new-wallet]")
    pg.fill(".sheet [name=name]", "Trezor ETH")
    pg.fill(".sheet [name=nickname]", "Vault")
    pg.click(".sheet [aria-label=Kind] button[data-value=onchain]")
    pg.select_option(".sheet [name=network]", "ethereum")
    pg.fill(".sheet [name=address]", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e")
    pg.fill(".sheet [name=tags]", "cold, Long-Term")
    pg.click(".sheet [aria-label='Second color'] button[data-value=custom]")
    pg.click(".sheet button[type=submit]")
    c = card(pg, "Vault")
    c.wait_for()
    assert c.locator(".name").inner_text() == "Trezor ETH"
    assert c.locator(".chip:not(.system)").all_inner_texts() == ["cold", "long-term"]
    assert pg.locator(".sheet").count() == 0


def test_seed_phrase_is_refused_and_not_echoed(super_page):
    pg = super_page
    open_window(pg, "wallets")
    pg.click("[data-action=new-wallet]")
    pg.fill(".sheet [name=name]", "Oops")
    pg.fill(".sheet [name=notes]", SEED_PHRASE_FREE)
    pg.click(".sheet button[type=submit]")
    err = pg.locator(".sheet .notice.error")
    err.wait_for()
    assert "recovery (seed) phrase" in err.inner_text() and "abandon" not in err.inner_text()
    assert pg.locator(".sheet").count() == 1  # nothing was saved; the form stays open


def test_set_balance_and_network_rule(super_page):
    pg = super_page
    open_window(pg, "wallets")
    wallet_action(pg, "Everyday ETH", "set-balance")
    pg.fill(".sheet [name=symbol]", "BTC")
    pg.fill(".sheet [name=amount]", "1")
    pg.click(".sheet button[type=submit]")
    pg.locator(".sheet .notice.error", has_text="WBTC").wait_for()
    pg.fill(".sheet [name=symbol]", "LINK")
    pg.fill(".sheet [name=amount]", "50.125")
    pg.click(".sheet button[type=submit]")
    pg.wait_for_selector(".sheet", state="detached")
    # The card refreshes after the sheet closes: wait for the new amount, then check it exactly.
    row = card(pg, "Everyday ETH").locator("tr", has_text="LINK").filter(has_text="50.125")
    row.wait_for()
    assert row.locator("td").nth(1).inner_text() == "50.125"


def test_group_by_coin(super_page):
    pg = super_page
    open_window(pg, "wallets")
    pg.click("[aria-label='Group by'] button[data-value=coin]")
    row = pg.locator(".window[data-panel=wallets] table.table tbody tr", has_text="USDC")
    row.wait_for()
    assert row.locator("td").nth(1).inner_text() == "1,645.5"
    assert row.locator(".held-in .chip").count() == 3


def test_delete_flows(super_page, server):
    pg = super_page
    open_window(pg, "wallets")
    # An empty wallet still asks first.
    pg.click("[data-action=new-wallet]")
    pg.fill(".sheet [name=name]", "Temp")
    pg.click(".sheet button[type=submit]")
    card(pg, "Temp").wait_for()
    wallet_action(pg, "Temp", "delete")
    assert "holds nothing" in pg.inner_text(".sheet")
    pg.click(".sheet [data-action=confirm-delete]")
    card(pg, "Temp").wait_for(state="detached")
    # Forcing needs the exact name; the button stays off until then.
    wallet_action(pg, "Paper portfolio", "delete")
    force = pg.locator(".sheet [data-action=force-delete]")
    assert force.is_disabled()
    pg.fill(".sheet [aria-label='Type the wallet name']", "practice")
    assert force.is_disabled()
    pg.keyboard.press("Escape")
    # Move everything into another wallet, then delete.
    wallet_action(pg, "Paper portfolio", "delete")
    pg.select_option(".sheet [aria-label='Move to']", label="Coinbase")
    pg.click(".sheet [data-action=move-delete]")
    card(pg, "Paper portfolio").wait_for(state="detached")
    assert card(pg, "Coinbase").locator("tr", has_text="DOGE").count() == 1


def test_archive_hides_and_show_archived_brings_back(super_page):
    pg = super_page
    open_window(pg, "wallets")
    wallet_action(pg, "Phantom", "archive")
    card(pg, "Phantom").wait_for(state="detached")
    pg.check("[aria-label='Show archived']")
    c = card(pg, "Phantom")
    c.wait_for()
    assert "status:archived" in c.locator(".chip.system").all_inner_texts()
    wallet_action(pg, "Phantom", "archive")  # unarchive
    pg.uncheck("[aria-label='Show archived']")
    card(pg, "Phantom").wait_for()


def test_drag_to_reorder_is_remembered(super_page):
    pg = super_page
    open_window(pg, "wallets")
    pg.keyboard.press("Control+Alt+ArrowUp")
    names = lambda: pg.locator(".wallet-card .nick").all_inner_texts()  # noqa: E731
    pg.wait_for_selector(".wallet-card")
    before = names()
    with pg.expect_response(lambda r: r.url.endswith("/api/me/wallet-order")):
        card(pg, before[-1]).drag_to(card(pg, before[0]), target_position={"x": 20, "y": 20})
    moved = names()
    assert moved[0] == before[-1]
    pg.reload()
    pg.wait_for_selector("body[data-session=ready]")
    pg.wait_for_selector(".wallet-card")
    assert names() == moved


# ---- transfers ---------------------------------------------------------------------------


def test_transfer_updates_the_other_windows(super_page):
    pg = super_page
    open_window(pg, "wallets")
    open_window(pg, "transfers")
    pg.click(".mode-toggle")  # tiled: both visible
    t = pg.locator(".window[data-panel=transfers]")
    assert "Simulated, no real funds move" in t.locator(".banner").inner_text()
    t.locator("[name=from]").select_option(label="Coinbase (exchange)")
    t.locator("[name=to]").select_option(label="Cold storage (Bitcoin)")
    t.locator("[name=symbol]").select_option("BTC")
    t.locator("[name=amount]").fill("0.0015")
    t.locator("[data-action=send]").click()
    pg.locator(".toast", has_text="Transfer recorded").wait_for()
    assert pg.locator(".toast", has_text="deposit or withdrawal page").count() == 1
    t.locator("tbody tr", has_text="0.0015 BTC").wait_for()
    assert "simulated" in t.locator("tbody tr").first.inner_text()
    # The Wallets window refreshed by itself.
    pg.wait_for_function("""() => [...document.querySelectorAll('.wallet-card')]
        .some(c => c.innerText.includes('Cold storage') && c.innerText.includes('1.1015'))""")
    pg.click(".mode-toggle")


def test_transfer_across_networks_is_refused_with_a_reason(super_page):
    pg = super_page
    open_window(pg, "transfers")
    t = pg.locator(".window[data-panel=transfers]")
    t.locator("[name=from]").select_option(label="Everyday ETH (Ethereum)")
    t.locator("[name=to]").select_option(label="Phantom (Solana)")
    assert "different networks" in t.locator(".hint").inner_text()
    t.locator("[name=symbol]").select_option("USDC")
    t.get_by_role("button", name="Max", exact=True).click()
    assert t.locator("[name=amount]").input_value() != ""
    t.locator("[data-action=send]").click()
    assert "bridge" in t.locator(".notice.error").inner_text()


# ---- overview ----------------------------------------------------------------------------


def test_overview_watchlist_currency_columns_and_chart(super_page):
    pg = super_page
    open_window(pg, "overview")
    o = pg.locator(".window[data-panel=overview]")
    o.locator("tr[data-symbol=BTC]").wait_for()
    assert o.locator(".total .big").inner_text().startswith("$")
    # Star a coin: it stays starred after a reload.
    with pg.expect_response(
        lambda r: "/api/me/preferences" in r.url and "watchlist" in (r.request.post_data or "")
    ):
        o.locator("[data-star=LINK]").click()
    pg.reload()  # straight away: the window just opened must still come back (pagehide save)
    pg.wait_for_selector("body[data-session=ready]")
    o = pg.locator(".window[data-panel=overview]")
    o.locator("[data-star=LINK].on").wait_for()
    # Yen: no decimals.
    o.locator("[aria-label=Currency]").select_option("jpy")
    # Function form: a bare string would be run with eval, which the app's CSP blocks.
    pg.wait_for_function("() => document.querySelector('.total .big')?.innerText.startsWith('¥')")
    assert "." not in o.locator(".total .big").inner_text()
    o.locator("[aria-label=Currency]").select_option("usd")
    # Hide a column.
    o.locator("[data-action=columns]").click()
    pg.uncheck(".menu [data-column=holdings]")
    pg.wait_for_function(
        "() => ![...document.querySelectorAll('.window[data-panel=overview] th')]"
        ".some(t => t.innerText.includes('HOLDINGS'))"
    )
    pg.keyboard.press("Escape")
    pg.mouse.click(5, 5)
    # The chart draws the recorded history; hover shows an exact price.
    o.locator("tr[data-symbol=BTC]").click()
    chart = o.locator("svg.chart")
    chart.wait_for()
    time.sleep(0.5)  # the chart scrolls itself into view (smoothly)
    assert pg.evaluate("""() => {
        const r = document.querySelector('svg.chart').getBoundingClientRect();
        const w = document.querySelector('.window[data-panel=overview] .window-body')
            .getBoundingClientRect();
        return r.top >= w.top && r.bottom <= w.bottom + 1; }""")  # visible, not below the fold
    assert chart.locator("path.line").count() == 1
    box = chart.bounding_box()
    pg.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
    tip = chart.locator("text.tip").text_content()  # SVG text: not an HTML element
    assert tip.startswith("$") and "·" in tip
    o.locator("[aria-label=Range] button[data-value='168']").click()
    o.locator("svg.chart").wait_for()
    no_null_text(pg)


# ---- audit -------------------------------------------------------------------------------


def test_audit_search(super_page):
    pg = super_page
    open_window(pg, "audit")
    a = pg.locator(".window[data-panel=audit]")
    a.locator("tbody tr").first.wait_for()
    a.locator("[aria-label='Search the audit log']").fill("wallet.create")
    pg.wait_for_function("""() => {
        const rows = [...document.querySelectorAll('.window[data-panel=audit] tbody tr')];
        return rows.length > 0 && rows.every(r => r.innerText.includes('wallet.create'));
    }""")


# ---- a read-only user --------------------------------------------------------------------


def test_viewer_sees_but_cannot_change(page, server, seeded):
    pw = server.make_user("readonly_ui", ["wallets.view"])
    sign_in(page, server.base_url, "readonly_ui", pw)
    open_window(page, "wallets")
    card(page, "Cold storage").wait_for()
    assert page.locator("[data-action=new-wallet]").count() == 0
    assert page.locator("[data-action=wallet-menu]").count() == 0
    assert page.locator(".wallet-card footer").count() == 0  # no prices.view: no values
    open_window(page, "transfers")
    assert page.locator(".window[data-panel=transfers] [data-action=send]").count() == 0
    page.locator(".window[data-panel=transfers] tbody tr").first.wait_for()
