"""8a in a real browser: wallpapers. Built-ins, a playing video, reduced motion, uploads
(picture and video through the file picker), dim and blur, delete."""

import subprocess

import pytest
from PIL import Image

from app.wallpapers import have_ffmpeg
from tests.ui.conftest import open_window, sign_in


def appearance(pg):
    open_window(pg, "settings")
    pg.click(".settings-nav [data-section=appearance]")
    pg.locator(".wallpaper-tile[data-wallpaper=none]").wait_for()
    return pg.locator(".window[data-panel=settings]")


def pick(pg, key):
    pg.locator(f".wallpaper-tile[data-wallpaper='{key}']").click()
    pg.locator(f".wallpaper[data-wallpaper='{key}']").wait_for(state="attached")


def test_builtin_wallpaper_and_it_stays(page, server):
    sign_in(page, server.base_url, "super", server.password)
    appearance(page)
    pick(page, "builtin:aurora")
    img = page.locator(".wallpaper img.wallpaper-media")
    assert img.get_attribute("src").endswith("/static/wallpapers/aurora.webp")
    page.wait_for_function("() => document.querySelector('.wallpaper img')?.naturalWidth === 2560")
    assert page.locator(".wallpaper-dim").evaluate("e => e.style.opacity") == "0.25"
    page.reload()
    page.wait_for_selector("body[data-session=ready]")
    page.locator(".wallpaper[data-wallpaper='builtin:aurora'] img").wait_for(state="attached")


def test_video_wallpaper_plays_and_respects_reduced_motion(page, server, chromium):
    sign_in(page, server.base_url, "super", server.password)
    appearance(page)
    pick(page, "builtin:drift")
    page.wait_for_function(
        "() => { const v = document.querySelector('.wallpaper video');"
        " return v && !v.paused && v.currentTime > 0.3 && v.muted; }",
        timeout=10000,
    )
    # Reduced motion on the device: the still, no video.
    calm = chromium.new_context(reduced_motion="reduce", viewport={"width": 1280, "height": 800})
    pg = calm.new_page()
    sign_in(pg, server.base_url, "super", server.password)
    pg.locator(".wallpaper[data-wallpaper='builtin:drift']").wait_for(state="attached")
    assert pg.locator(".wallpaper video").count() == 0
    assert pg.locator(".wallpaper img").get_attribute("src").endswith("drift.poster.webp")
    calm.close()
    # And "Still" in the settings does the same here.
    page.locator(".window[data-panel=settings] .segmented button", has_text="Still").click()
    page.locator(".wallpaper[data-motion=off] img").wait_for(state="attached")


def test_upload_a_picture_tune_it_and_delete_it(page, server, tmp_path):
    sign_in(page, server.base_url, "super", server.password)
    w = appearance(page)
    f = tmp_path / "Mountains.png"
    Image.new("RGB", (1600, 900), (40, 90, 140)).save(f)
    with page.expect_file_chooser() as fc:
        w.locator("[data-action=upload-wallpaper]").click()
    fc.value.set_files(str(f))
    page.locator(".toast", has_text="Wallpaper added").wait_for()
    tile = w.locator(".wallpaper-tile.selected", has_text="Mountains")
    tile.wait_for()
    assert "yours" in tile.inner_text()
    src = page.locator(".wallpaper img").get_attribute("src")
    assert src.startswith("/api/wallpapers/") and src.endswith("/file")
    page.wait_for_function("() => document.querySelector('.wallpaper img')?.naturalWidth === 1600")
    # Dim and blur preview at once and save.
    w.locator("[data-action=wallpaper-dim]").fill("60")
    assert page.locator(".wallpaper-dim").evaluate("e => e.style.opacity") == "0.6"
    w.locator("[data-action=wallpaper-blur]").fill("8")
    page.wait_for_function(
        "() => document.querySelector('.wallpaper img')?.style.filter === 'blur(8px)'"
    )
    page.screenshot(path="tests/ui/screens/wallpaper_upload.png")
    w.locator("[data-action=delete-wallpaper]").click()
    page.locator(".toast", has_text="Wallpaper deleted").wait_for()
    w.locator(".wallpaper-tile.selected[data-wallpaper=none]").wait_for()
    assert page.locator(".wallpaper .wallpaper-media").count() == 0


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg isn't installed")
def test_upload_a_video(page, server, tmp_path):
    clip = tmp_path / "Waves.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc2=size=640x360:rate=25", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(clip)], check=True,
    )  # fmt: skip
    sign_in(page, server.base_url, "super", server.password)
    w = appearance(page)
    with page.expect_file_chooser() as fc:
        w.locator("[data-action=upload-wallpaper]").click()
    fc.value.set_files(str(clip))
    page.locator(".toast", has_text="Wallpaper added").wait_for(timeout=60000)
    w.locator(".wallpaper-tile.selected .badge", has_text="Video").wait_for()
    # Motion is a saved preference (an earlier test may have chosen Still): animate.
    w.locator(".segmented button", has_text="Animate").click()
    page.wait_for_function(
        "() => { const v = document.querySelector('.wallpaper video');"
        " return v && !v.paused && v.currentTime > 0.2; }",
        timeout=10000,
    )
    src = page.locator(".wallpaper video").get_attribute("src")
    assert src.startswith("/api/wallpapers/") and src.endswith("/file")


def test_a_bad_file_is_refused_with_a_reason(page, server, tmp_path):
    sign_in(page, server.base_url, "super", server.password)
    w = appearance(page)
    f = tmp_path / "notes.png"
    f.write_bytes(b"this is not a picture, whatever the name says" * 3)
    with page.expect_file_chooser() as fc:
        w.locator("[data-action=upload-wallpaper]").click()
    fc.value.set_files(str(f))
    w.locator(".notice.error", has_text="Not a picture or video").wait_for()
