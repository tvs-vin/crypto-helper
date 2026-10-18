"""8b in a real browser: installing a theme bundle (wallpaper + icons) from the file picker."""

from pathlib import Path

from app import theme_bundle
from tests.ui.conftest import open_window, sign_in

EXAMPLE = Path(__file__).parents[2] / "examples/themes/sunset.ctheme.d"
CHART = "M3.5 11l2.5-3.5 2.5 2 2-4 2.5 2.5"


def test_install_a_bundle_and_use_its_wallpaper_and_icons(page, server, tmp_path):
    bundle = tmp_path / "sunset.ctheme"
    bundle.write_bytes(theme_bundle.pack(EXAMPLE))
    sign_in(page, server.base_url, "super", server.password)
    open_window(page, "settings")
    page.click(".settings-nav [data-section=appearance]")
    w = page.locator(".window[data-panel=settings]")
    with page.expect_file_chooser() as fc:
        w.locator("[data-action=upload-theme]").click()
    fc.value.set_files(str(bundle))
    page.locator(".toast", has_text="Theme installed").wait_for()
    accent = page.evaluate(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--c-accent').trim()"
    )
    assert accent.lower() == "#f28c55"
    card = w.locator(".theme-card-wrap", has_text="Sunset")
    assert "wallpaper" in card.inner_text() and "2 icons" in card.inner_text()

    # Its icons: the chart (vector) in the launcher, the wallet (a PNG) as a picture.
    page.click("[data-action=launcher]")
    chart = page.locator(".menu-item[data-panel=overview] svg path").nth(1)
    assert chart.get_attribute("d") == CHART
    wallet = page.locator(".menu-item[data-panel=wallets] img.icon-image")
    assert wallet.get_attribute("src").startswith("data:image/png;base64,")
    page.keyboard.press("Escape")

    # "Theme's own" wallpaper is the bundle's dusk.
    tile = w.locator(".wallpaper-tile[data-wallpaper=theme]", has_text="Theme's own (dusk)")
    tile.click()
    page.wait_for_function(
        "() => document.querySelector('.wallpaper img')?.src.includes('/api/wallpapers/')"
        " && document.querySelector('.wallpaper img').naturalWidth === 2560"
    )
    page.locator(".wallpaper img").evaluate("img => img.decode()")  # decoded and ready to paint
    page.wait_for_timeout(300)
    page.screenshot(path="tests/ui/screens/theme_bundle.png")

    # Download gives the bundle back.
    with page.expect_download() as dl:
        card.locator("[data-action=download-theme]").click()
    data = Path(dl.value.path()).read_bytes()
    b = theme_bundle.read(data)
    assert b.wallpapers and set(b.icons) == {"wallet"}

    # Back to Dark: the built-in icons return, and "theme's own" becomes Dark's Aurora.
    w.locator(".theme-card[data-theme=dark]").click()
    page.wait_for_function(
        "() => document.querySelector('.wallpaper img')?.src"
        ".endsWith('/static/wallpapers/aurora.webp')"
    )
    page.click("[data-action=launcher]")
    assert page.locator(".menu-item[data-panel=wallets] img.icon-image").count() == 0
