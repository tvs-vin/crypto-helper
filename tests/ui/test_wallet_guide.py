"""8c in a real browser: guided wallet setup, start to finish, and its safety checks."""

from tests.ui.conftest import open_window, sign_in
from tests.ui.seed import SEED_PHRASE_FREE

BTC = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
ETH = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"


def guide(pg):
    open_window(pg, "wallets")
    w = pg.locator(".window[data-panel=wallets]")
    w.locator("[data-action=wallet-guide]").click()
    s = pg.locator(".sheet")
    s.locator(".guide-kinds").wait_for()
    return s


def tick_all_and_next(s):
    for box in s.locator(".guide-checks input").all():
        box.check()
    s.locator("[data-action=guide-next]").click()


def test_hardware_wallet_start_to_finish(page, server):
    sign_in(page, server.base_url, "super", server.password)
    s = guide(page)
    assert s.locator(".guide-kind").count() == 4
    s.locator(".guide-kind[data-kind=hardware]").click()
    # You can't skip the safety steps.
    s.locator("[data-action=guide-next]").click()
    s.locator(".guide-warn:not(.hidden)").wait_for()
    assert "Get your hardware wallet safely" in s.inner_text()
    tick_all_and_next(s)
    assert "Look after your recovery phrase" in s.inner_text()
    assert "Crypto Helper will never ask for it" in s.inner_text()
    tick_all_and_next(s)
    assert "Test it before you trust it" in s.inner_text()
    tick_all_and_next(s)
    s.locator("[name=name]").fill("Ledger savings")
    s.locator("[name=provider]").fill("Ledger")
    s.locator("[name=network]").select_option("bitcoin")
    s.locator("[name=address]").fill(BTC)
    page.screenshot(path="tests/ui/screens/wallet_guide.png")
    s.locator("[data-action=guide-add]").click()
    page.locator(".toast", has_text="Wallet added").wait_for()
    card = page.locator(".wallet-card", has_text="Ledger savings")
    card.wait_for()
    assert "guided" in card.inner_text()


def test_exchange_skips_the_phrase_step_and_needs_no_address(page, server):
    sign_in(page, server.base_url, "super", server.password)
    s = guide(page)
    s.locator(".guide-kind[data-kind=exchange]").click()
    assert s.locator(".guide-steps li").count() == 4  # no recovery phrase for an exchange
    tick_all_and_next(s)
    assert "Test it before you trust it" in s.inner_text()
    tick_all_and_next(s)
    assert s.locator("[name=address]").count() == 0 and s.locator("[name=network]").count() == 0
    s.locator("[name=name]").fill("Coinbase account")
    s.locator("[name=provider]").fill("Coinbase")
    s.locator("[data-action=guide-add]").click()
    page.locator(".toast", has_text="Wallet added").wait_for()
    page.locator(".wallet-card", has_text="Coinbase account").wait_for()


def _to_add_form(s, kind="phone"):
    s.locator(f".guide-kind[data-kind={kind}]").click()
    for _ in range(3):
        tick_all_and_next(s)


def test_a_pasted_recovery_phrase_is_refused_and_nothing_saved(page, server):
    sign_in(page, server.base_url, "super", server.password)
    s = guide(page)
    _to_add_form(s)
    s.locator("[name=name]").fill("Phrase test")
    s.locator("[name=network]").select_option("ethereum")
    s.locator("[name=address]").fill(SEED_PHRASE_FREE)
    s.locator("[data-action=guide-add]").click()
    err = s.locator(".notice.error")
    err.wait_for()
    assert "recovery phrase" in err.inner_text().lower() or "seed" in err.inner_text().lower()
    assert SEED_PHRASE_FREE not in err.inner_text()  # never echoed
    page.locator(".sheet [aria-label=Close]").click()
    assert page.locator(".wallet-card", has_text="Phrase test").count() == 0


def test_an_address_on_the_wrong_network_is_refused(page, server):
    sign_in(page, server.base_url, "super", server.password)
    s = guide(page)
    _to_add_form(s)
    s.locator("[name=name]").fill("Wrong network")
    s.locator("[name=network]").select_option("bitcoin")
    s.locator("[name=address]").fill(ETH)
    s.locator("[data-action=guide-add]").click()
    s.locator(".notice.error").wait_for()
    assert page.locator(".wallet-card", has_text="Wrong network").count() == 0
