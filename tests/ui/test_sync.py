"""11a in a real browser: add a read-only connection, link a wallet, sync it."""

from tests.ui.conftest import open_window, sign_in


def settings_section(page, name):
    open_window(page, "settings")
    page.click(f".settings-nav [data-section={name}]")
    return page.locator(".window[data-panel=settings]")


def test_connect_link_and_sync(page, server):
    sign_in(page, server.base_url, "super", server.password)
    s = settings_section(page, "connections")
    # Each exchange asks for its own fields (Coinbase: a key name and a multi-line private key).
    s.locator("[name=exchange]").select_option("coinbase")
    s.locator("[name=cred_key_name]").wait_for()
    assert s.locator("textarea[name=cred_private_key]").count() == 1
    assert "view permission only" in s.inner_text() and "Coinbase guide" in s.inner_text()
    page.screenshot(path="tests/ui/screens/connections_coinbase.png")
    s.locator("[name=exchange]").select_option("demo")
    s.locator("[name=connection_label]").fill("Practice account")
    # A key that can trade: refused, with the reason, and nothing saved.
    s.locator("[name=cred_key]").fill("trade-key-123456789")
    s.locator("[name=cred_secret]").fill("whatever-secret-here")
    s.locator("[data-action=add-connection]").click()
    s.locator(".notice.error", has_text="can trade or move funds").wait_for()
    # One the exchange can't vouch for: confirm first.
    s.locator("[name=cred_key]").fill("unknown-key-123456789")
    s.locator("[data-action=add-connection]").click()
    s.locator("[name=confirm_read_only]").wait_for()
    s.locator("[name=confirm_read_only]").check()
    s.locator("[data-action=add-connection]").click()
    page.locator(".toast", has_text="Connection saved").wait_for()
    row = s.locator(".connection-row", has_text="Practice account")
    row.wait_for()
    assert "…6789" in row.inner_text() and "confirmed view-only by super" in row.inner_text()
    assert s.locator("[name=cred_key]").input_value() == ""  # cleared from the screen
    page.screenshot(path="tests/ui/screens/connections.png")

    # An exchange wallet, linked to it.
    server.api("POST", "/api/wallets", {"name": "Practice exchange", "kind": "exchange"},
               server.admin_cookie())  # fmt: skip
    open_window(page, "wallets")
    w = page.locator(".window[data-panel=wallets]")
    card = w.locator(".wallet-card", has_text="Practice exchange")
    card.wait_for()
    card.locator("[data-action=wallet-menu]").click()
    page.locator(".menu [data-action=sync-from]").click()
    w.locator("label.choice", has_text="Sync from Practice account").click()
    w.locator("[data-action=save-source]").click()
    page.locator(".toast", has_text="Practice exchange synced").wait_for()
    card.locator(".badge.ok", has_text="synced").wait_for()
    text = card.inner_text()
    assert "BTC" in text and "0.5" in text and "Not tracked: 7 ZZZ" in text
    assert "From Demo exchange: Practice account" in text
    card.scroll_into_view_if_needed()
    page.screenshot(path="tests/ui/screens/synced_wallet.png")
    # Synced: the menu offers Sync now instead of setting a balance.
    card.locator("[data-action=wallet-menu]").click()
    assert page.locator(".menu [data-action=set-balance]").count() == 0
    page.locator(".menu [data-action=sync-now]").click()
    page.locator(".toast", has_text="Nothing changed").wait_for()


def test_bitcoin_wallet_from_an_xpub(page, server):
    """11c: an on-chain wallet syncs from an xpub (a local fake Bitcoin server, no network)."""
    from tests.test_chains import ZPUB, Chain, derive

    chain = Chain()
    try:
        cookie = server.admin_cookie()
        server.api("PUT", "/api/sync/chains", {"esplora_url": chain.url}, cookie)
        chain.btc[derive(ZPUB, "wpkh", 0, 0)] = (12_500_000, 0, 1)
        chain.btc[derive(ZPUB, "wpkh", 1, 0)] = (500_000, 0, 1)
        server.api("POST", "/api/wallets", {"name": "Cold storage", "kind": "onchain",
                                            "network": "bitcoin"}, cookie)  # fmt: skip
        sign_in(page, server.base_url, "super", server.password)
        open_window(page, "wallets")
        w = page.locator(".window[data-panel=wallets]")
        card = w.locator(".wallet-card", has_text="Cold storage")
        card.wait_for()
        card.locator("[data-action=wallet-menu]").click()
        page.locator(".menu [data-action=sync-from]").click()
        w.locator("label.choice", has_text="extended public key").click()
        # An extended PRIVATE key is refused, with why, and not kept.
        w.locator("[name=watch_xpub]").fill("xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6c"
                                            "q3jPPqjiChkVvvNKmPGJxWUtL6LZNqEXrgLaxFbTmNfZ5ruHAMJ"
                                            "GkxEGxV7oi")  # fmt: skip
        w.locator("[data-action=save-source]").click()
        w.locator(".notice.error", has_text="PRIVATE key").wait_for()
        w.locator("[name=watch_xpub]").fill(ZPUB)
        page.screenshot(path="tests/ui/screens/xpub_sheet.png")
        w.locator("[data-action=save-source]").click()
        page.locator(".toast", has_text="Cold storage synced").wait_for()
        card.locator(".badge.ok", has_text="synced").wait_for()
        text = card.inner_text()
        assert "0.13" in text and "From Bitcoin zpub…tZYs" in text
        assert "2 addresses in use · Native SegWit (bc1q…)" in text  # what the scan found
        page.screenshot(path="tests/ui/screens/xpub_wallet.png")
    finally:
        chain.srv.shutdown()
