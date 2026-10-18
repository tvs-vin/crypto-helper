"""6c in a real browser: Settings (account, appearance, display, prices, system) and Users."""

import json
import time
from pathlib import Path

import pyotp

from tests.ui.conftest import open_window, sign_in

DARK = json.loads((Path(__file__).resolve().parents[2] / "app/web/themes/dark.ctheme").read_text())


def settings(pg, section):
    if not pg.locator(".window[data-panel=settings]").count():
        open_window(pg, "settings")
    pg.click(f".settings-nav [data-section={section}]")
    return pg.locator(".settings-main")


def accent(pg):
    return pg.evaluate(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--c-accent').trim().toLowerCase()"
    )


# ---- account -----------------------------------------------------------------------------


def test_turn_on_2fa_with_the_qr_code_then_sign_in_with_a_code(page, server, chromium):
    pw = server.make_user("qr_ui", [])
    sign_in(page, server.base_url, "qr_ui", pw)
    assert page.locator(".user-chip .dot").count() == 1  # "2FA off" marker
    m = settings(page, "account")
    page.click("[data-action=enable-2fa]")
    qr = m.locator("img.qr")
    qr.wait_for()
    assert qr.evaluate("img => img.complete && img.naturalWidth > 100")  # a real image
    secret = m.locator(".copyable .input").input_value()
    m.locator("[aria-label='Code from the app']").fill(pyotp.TOTP(secret).now())
    m.locator("[name=current_password]").fill("not-my-password")  # asked again: refused
    page.click("[data-action=confirm-2fa]")
    m.locator(".notice.error", has_text="Password is incorrect").wait_for()
    m.locator("[name=current_password]").fill(pw)
    page.click("[data-action=confirm-2fa]")
    codes = m.locator(".codes li")
    codes.first.wait_for()
    assert codes.count() == 10
    assert page.locator(".user-chip .dot").count() == 0  # cleared straight away
    page.click("[data-action=codes-saved]")
    m.locator(".badge.ok", has_text="on").wait_for()
    # Another device now needs the code (a later window, so it isn't a replay).
    context = chromium.new_context()
    other = context.new_page()
    other.goto(server.base_url + "/")
    other.fill("#login-username", "qr_ui")
    other.fill("#login-password", pw)
    other.click("button[type=submit]")
    other.fill("#login-code", pyotp.TOTP(secret).at(time.time() + 30))
    other.click("button[type=submit]")
    other.wait_for_selector("body[data-session=ready]")
    context.close()


def test_change_password(page, server, chromium):
    pw = server.make_user("pwchange_ui", [])
    sign_in(page, server.base_url, "pwchange_ui", pw)
    m = settings(page, "account")
    m.locator("[name=current]").fill(pw)
    m.locator("[name=new]").fill("a-brand-new-passphrase")
    m.locator("[name=repeat]").fill("a-brand-new-passphrase")
    m.get_by_role("button", name="Change password").click()
    page.locator(".toast", has_text="Password changed").wait_for()
    context = chromium.new_context()
    other = context.new_page()
    sign_in(other, server.base_url, "pwchange_ui", "a-brand-new-passphrase")
    context.close()


def test_see_and_end_other_sessions(page, server, chromium):
    pw = server.make_user("sessions_ui", [])
    context = chromium.new_context()
    other = context.new_page()
    sign_in(other, server.base_url, "sessions_ui", pw)
    sign_in(page, server.base_url, "sessions_ui", pw)
    m = settings(page, "account")
    rows = m.locator(".sessions li")
    rows.nth(1).wait_for()
    assert rows.count() == 2 and m.locator(".badge.ok", has_text="this device").count() == 1
    m.locator("[data-action=revoke-others]").click()
    page.locator(".toast", has_text="Signed out everywhere else").wait_for()
    assert rows.count() == 1
    open_window(other, "settings")  # the other browser's next request needs a new sign-in
    other.wait_for_selector("#login-password")
    context.close()


# ---- appearance --------------------------------------------------------------------------


def write_theme(tmp_path, name, **colors):
    t = json.loads(json.dumps(DARK))
    t["name"] = name
    t["colors"].update(colors)
    p = tmp_path / f"{name.lower()}.ctheme"
    p.write_text(json.dumps(t))
    return p


def test_upload_preview_save_and_keep_a_theme(page, server, tmp_path):
    pw = server.make_user("upload_ui", [])
    sign_in(page, server.base_url, "upload_ui", pw)
    settings(page, "appearance")
    page.set_input_files("input[type=file]", str(write_theme(tmp_path, "Ember", accent="#F2703A")))
    page.locator(".notice", has_text="Previewing").wait_for()
    assert accent(page) == "#f2703a"  # previewing, not saved
    page.click("[data-action=discard-theme]")
    assert accent(page) == "#7545fc"
    page.set_input_files("input[type=file]", str(write_theme(tmp_path, "Ember", accent="#F2703A")))
    page.click("[data-action=save-theme]")
    page.locator(".theme-card", has_text="Ember").wait_for()
    page.reload()
    page.wait_for_selector("body[data-session=ready]")
    assert accent(page) == "#f2703a"  # in use and remembered


def test_a_bad_theme_file_is_refused_before_anything_changes(page, server, tmp_path):
    pw = server.make_user("badtheme_ui", [])
    sign_in(page, server.base_url, "badtheme_ui", pw)
    settings(page, "appearance")
    page.set_input_files(
        "input[type=file]", str(write_theme(tmp_path, "Evil", accent="url(https://evil.example/x)"))
    )
    err = page.locator(".settings-main .notice.error")
    err.wait_for()
    assert "isn't a valid theme" in err.inner_text() and accent(page) == "#7545fc"
    junk = tmp_path / "junk.ctheme"
    junk.write_text("not json at all")
    page.set_input_files("input[type=file]", str(junk))
    assert "must be JSON" in page.locator(".settings-main .notice.error").inner_text()


def test_download_the_template(page, server):
    pw = server.make_user("download_ui", [])
    sign_in(page, server.base_url, "download_ui", pw)
    settings(page, "appearance")
    with page.expect_download() as d:
        page.get_by_role("button", name="Download the template").click()
    assert d.value.suggested_filename == "template.ctheme"
    assert json.loads(Path(d.value.path()).read_text())["format"] == "crypto-helper-theme"


def test_admin_publishes_a_theme_for_everyone(page, server, tmp_path, chromium):
    pw = server.make_user("publisher_ui", ["themes.publish"])
    sign_in(page, server.base_url, "publisher_ui", pw)
    settings(page, "appearance")
    page.set_input_files("input[type=file]", str(write_theme(tmp_path, "House", accent="#22AA88")))
    page.click("[data-action=save-theme]")
    card = page.locator(".theme-card-wrap", has_text="House")
    card.wait_for()
    card.locator("[data-action=publish]").click()
    card.locator("text=published").wait_for()
    other_pw = server.make_user("viewer_theme_ui", [])
    context = chromium.new_context()
    other = context.new_page()
    sign_in(other, server.base_url, "viewer_theme_ui", other_pw)
    settings(other, "appearance")
    shared = other.locator(".theme-card", has_text="House")
    shared.wait_for()
    assert "by publisher_ui" in shared.inner_text()
    shared.click()
    other.wait_for_function(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--c-accent').trim().toLowerCase() === '#22aa88'"
    )
    context.close()


# ---- display -----------------------------------------------------------------------------


def test_watchlist_and_reset_layout(page, server):
    pw = server.make_user("display_ui", ["prices.view"])
    sign_in(page, server.base_url, "display_ui", pw)
    m = settings(page, "display")
    add = m.locator("[aria-label='Add to watchlist']")
    add.fill("sol")
    add.press("Enter")
    m.locator(".chip", has_text="SOL").wait_for()
    m.locator("[aria-label='Remove SOL']").click()
    m.locator(".chip", has_text="SOL").wait_for(state="detached")
    open_window(page, "overview")
    page.click(".task[data-panel=settings]")  # bring Settings back in front of Overview
    page.click("[data-action=reset-layout]")
    page.wait_for_function("() => !document.querySelector('.window')")


# ---- prices and system -------------------------------------------------------------------


def test_price_settings_and_an_extra_coin(page, server):
    pw = server.make_user("pricesadmin_ui", ["prices.manage", "prices.view"])
    sign_in(page, server.base_url, "pricesadmin_ui", pw)
    m = settings(page, "prices")
    m.locator("[name=keep]").fill("48")
    m.locator("[data-action=save-history]").click()
    page.locator(".toast", has_text="saved").wait_for()
    m = settings(page, "prices")  # re-open: the value came back from the server
    page.wait_for_function(
        "() => document.querySelector('.settings-main [name=keep]')?.value === '48'"
    )
    m.locator("[aria-label='CoinGecko id']").fill("fake-one")  # the mock knows a look-alike
    m.locator("[data-action=add-coin]").click()
    m.locator(".notice.warn", has_text="also use the symbol").wait_for()
    m.locator("[data-action=confirm-coin]").click()
    page.locator(".toast", has_text="Coin added").wait_for()
    m.locator(".sessions li", has_text="FAKE").wait_for()


def test_system_section_only_for_super(page, server, chromium):
    sign_in(page, server.base_url, "super", server.password)
    m = settings(page, "system")
    m.locator(".stat", has_text="Database").wait_for()
    assert "current" in m.locator(".stat", has_text="Database").inner_text()
    assert m.locator(".commands input").first.input_value() == "crypto-helper update"
    pw = server.make_user("notsuper_ui", ["users.manage", "audit.view"])
    context = chromium.new_context()
    other = context.new_page()
    sign_in(other, server.base_url, "notsuper_ui", pw)
    open_window(other, "settings")
    assert other.locator(".settings-nav [data-section=system]").count() == 0
    context.close()


# ---- users -------------------------------------------------------------------------------


def test_create_edit_deactivate_and_delete_a_user(page, server):
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "users")
    page.click("[data-action=new-user]")
    page.fill(".sheet [name=username]", "made_in_ui")
    page.fill(".sheet [name=password]", "made-in-ui-passphrase")
    page.select_option(".sheet [aria-label=Preset]", "viewer")
    page.click("[data-action=save-user]")
    row = page.locator("tr[data-key=made_in_ui]")
    row.wait_for()
    assert "wallets.view" in row.inner_text() and "wallets.edit" not in row.inner_text()
    row.locator("[data-action=user-menu]").click()
    page.click(".menu [data-action=edit]")
    page.locator(".sheet input[value='audit.view']").check()
    page.click("[data-action=save-user]")
    page.wait_for_function(
        "() => document.querySelector('tr[data-key=made_in_ui]')?.innerText.includes('audit.view')"
    )
    page.locator("tr[data-key=made_in_ui] [data-action=user-menu]").click()
    page.click(".menu [data-action=toggle]")
    page.wait_for_function(
        "() => document.querySelector('tr[data-key=made_in_ui]')?.innerText.includes('deactivated')"
    )
    page.locator("tr[data-key=made_in_ui] [data-action=user-menu]").click()
    page.click(".menu [data-action=delete]")
    page.click("[data-action=confirm-delete-user]")
    page.locator("tr[data-key=made_in_ui]").wait_for(state="detached")


def test_managers_cant_grant_what_they_dont_hold(page, server):
    pw = server.make_user("manager_ui", ["users.manage", "wallets.view"])
    sign_in(page, server.base_url, "manager_ui", pw)
    open_window(page, "users")
    assert page.locator("tr[data-key=super] [data-action=user-menu]").count() == 0
    assert page.locator("tr[data-key=manager_ui] [data-action=user-menu]").count() == 0
    page.click("[data-action=new-user]")
    page.locator(".sheet input[value='audit.view']").wait_for()
    assert page.locator(".sheet input[value='audit.view']").is_disabled()
    assert not page.locator(".sheet input[value='wallets.view']").is_disabled()
