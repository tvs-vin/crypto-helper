"""8b: theme bundles (.ctheme zips with wallpapers and icons), and the CLI that makes them."""

import base64
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from app import theme_bundle, themes
from tests.conftest import H
from tests.wallet_helpers import user_with

EXAMPLE = Path(__file__).parents[1] / "examples/themes/sunset.ctheme.d"
UP = {**H, "Content-Type": "application/octet-stream"}
THEME = json.loads((EXAMPLE / "theme.json").read_text())


def zip_of(files: dict, *, mutate=None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED  # per file: ZipInfo defaults to stored
            if mutate:
                mutate(name, info)
            zf.writestr(info, content)
    return out.getvalue()


def minimal(**extra) -> dict:
    t = {k: v for k, v in THEME.items() if k not in ("icons", "icon_images", "wallpaper")}
    return {**t, **extra}


def upload(c, data: bytes):
    return c.post("/api/themes/upload", content=data, headers=UP)


# ---- happy path ------------------------------------------------------------------------------


def test_example_bundle_installs_with_its_wallpaper_and_icons(logged_in, app):
    r = upload(logged_in, theme_bundle.pack(EXAMPLE))
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["bundle"] and t["icons"] == 2 and t["wallpaper"].startswith("user:")
    data = logged_in.get(f"/api/themes/{t['id']}").json()
    assert data["icons"]["chart"] == THEME["icons"]["chart"]
    png = base64.b64decode(data["icon_images"]["wallet"].split(",", 1)[1])
    assert png.startswith(b"\x89PNG")  # re-encoded by the server
    wid = int(data["wallpaper"].removeprefix("user:"))
    f = logged_in.get(f"/api/wallpapers/{wid}/file")
    assert f.status_code == 200 and f.headers["content-type"] == "image/webp"
    # The theme's wallpaper isn't in the general list (it belongs to the theme).
    assert all(w["id"] != wid for w in logged_in.get("/api/wallpapers").json()["uploaded"])


def test_theme_wallpaper_is_private_until_the_theme_is_published(logged_in, app):
    t = upload(logged_in, theme_bundle.pack(EXAMPLE)).json()
    wid = int(t["wallpaper"].removeprefix("user:"))
    other = user_with(app, logged_in, "other", ["wallets.view"])
    assert other.get(f"/api/wallpapers/{wid}/file").status_code == 404
    assert (
        logged_in.post(
            f"/api/themes/{t['id']}/publish", json={"published": True}, headers=H
        ).status_code
        == 200
    )
    assert other.get(f"/api/wallpapers/{wid}/file").status_code == 200
    # A theme's wallpaper goes with the theme, not on its own.
    assert logged_in.delete(f"/api/wallpapers/{wid}", headers=H).status_code == 409


def test_download_round_trip(logged_in):
    t = upload(logged_in, theme_bundle.pack(EXAMPLE)).json()
    r = logged_in.get(f"/api/themes/{t['id']}/bundle")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="sunset.ctheme"' in r.headers["content-disposition"]
    b = theme_bundle.read(r.content)
    back = json.loads(b.theme_json)
    assert back["wallpaper"].startswith("wallpapers/") and back["wallpaper"] in b.wallpapers
    assert "icon_images" not in back and set(b.icons) == {"wallet"}
    again = upload(logged_in, r.content)
    assert again.status_code == 201, again.text


def test_deleting_the_theme_removes_its_wallpaper_files(logged_in, app):
    t = upload(logged_in, theme_bundle.pack(EXAMPLE)).json()
    base = Path(app.state.settings.state_dir) / "wallpapers"
    assert len(list(base.iterdir())) == 2  # the picture and its poster
    assert logged_in.delete(f"/api/themes/{t['id']}", headers=H).status_code == 204
    assert list(base.iterdir()) == []


def test_plain_json_themes_still_work_and_may_use_a_builtin_wallpaper(logged_in):
    r = upload(logged_in, json.dumps(minimal(wallpaper="builtin:dusk")).encode())
    assert r.status_code == 201, r.text
    assert not r.json()["bundle"] and r.json()["wallpaper"] == "builtin:dusk"


# ---- hostile bundles -------------------------------------------------------------------------


def _symlink(name, info):
    if name == "wallpapers/a.png":
        info.external_attr = 0o120777 << 16


def encrypted(data: bytes) -> bytes:
    """Python's zip writer clears the "encrypted" flag, so set it in the bytes, as a hostile
    file would: bit 0 of the flags in every local header and central directory entry."""
    b = bytearray(data)
    for sig, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = b.find(sig)
        while i != -1:
            b[i + offset] |= 0x1
            i = b.find(sig, i + 4)
    return bytes(b)


TJ = json.dumps(minimal()).encode()


@pytest.mark.parametrize(
    "files, mutate, message",
    [
        ({"theme.json": TJ, "../escape.txt": b"x"}, None, "may only contain"),
        # An absolute name (never a real system path, even inside a zip: see CLAUDE.md).
        ({"theme.json": TJ, "/absolute-name.txt": b"x"}, None, "may only contain"),
        ({"theme.json": TJ, "wallpapers/../../x.png": b"x"}, None, "may only contain"),
        ({"theme.json": TJ, "index.html": b"<script>"}, None, "may only contain"),
        ({"theme.json": TJ, "icons/wallet.svg": b"<svg/>"}, None, "may only contain"),
        ({"theme.json": TJ, "wallpapers/a.png": b"x"}, _symlink, "links"),
        ({"wallpapers/a.png": b"x"}, None, "no theme.json"),
        (
            {"theme.json": TJ, **{f"wallpapers/w{i}.png": b"x" for i in range(6)}},
            None,
            "at most 5 wallpapers",
        ),
        (
            {"theme.json": TJ, **{f"icons/a{chr(97 + i)}.png": b"x" for i in range(60)}},
            None,
            "at most 60 files",
        ),
        (
            {"theme.json": TJ, "wallpapers/bomb.png": b"\x00" * (5 * 1024 * 1024)},
            None,
            "suspiciously",
        ),
    ],
)
def test_hostile_bundles_are_refused(logged_in, files, mutate, message):
    r = upload(logged_in, zip_of(files, mutate=mutate))
    assert r.status_code == 422 and message in r.json()["detail"], r.text


def test_encrypted_bundles_are_refused(logged_in):
    r = upload(logged_in, encrypted(zip_of({"theme.json": TJ})))
    assert r.status_code == 422 and "encrypted" in r.json()["detail"]


def test_not_a_zip_and_not_json(logged_in):
    r = upload(logged_in, b"PK\x03\x04" + b"garbage" * 20)
    assert r.status_code == 422 and "readable zip" in r.json()["detail"]
    r = upload(logged_in, b"<html>")
    assert r.status_code == 422


@pytest.mark.parametrize(
    "theme, files, message",
    [
        (minimal(wallpaper="wallpapers/missing.png"), {}, "isn't in the bundle"),
        (minimal(wallpaper="user:1"), {}, "built-in one here"),
        (minimal(icons={"wallet": ["M0 0<script>"]}), {}, "shape commands only"),
        (minimal(icons={"nosuchicon": ["M0 0h1"]}), {}, "icons"),
        (minimal(), {"icons/nosuchicon.png": b"\x89PNG"}, "no icon is called"),
        (minimal(), {"icons/wallet.png": b"GIF89a fake"}, "must be PNG"),
        (minimal(), {"icons/wallet.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 40}, "couldn't be read"),
        (minimal(icon_images={"wallet": "data:image/svg+xml;base64,PHN2Zy8+"}), {}, "PNG data URI"),
        (minimal(colors={**THEME["colors"], "accent": "url(x)"}), {}, "hex color"),
    ],
)
def test_bad_contents_are_refused_without_echo(logged_in, theme, files, message):
    r = upload(logged_in, zip_of({"theme.json": json.dumps(theme).encode(), **files}))
    assert r.status_code == 422, r.text
    assert message in r.text
    assert "<script>" not in r.text and "url(x)" not in r.text


def test_plain_json_cant_point_at_bundle_files_or_uploads(logged_in):
    for wallpaper in ("wallpapers/x.png", "user:3"):
        r = upload(logged_in, json.dumps(minimal(wallpaper=wallpaper)).encode())
        assert r.status_code == 422


def test_a_bad_wallpaper_inside_a_bundle_names_the_file(logged_in):
    r = upload(logged_in, zip_of({"theme.json": TJ, "wallpapers/nope.png": b"not a picture" * 10}))
    assert r.status_code == 422 and "wallpapers/nope.png" in r.json()["detail"]


# ---- icons stay in step with the browser ------------------------------------------------------


def test_icon_names_match_the_browser():
    js = (Path(__file__).parents[1] / "app/web/js/dom.js").read_text()
    block = re.search(r"const ICONS = \{(.*?)\n\};", js, re.S).group(1)
    assert set(re.findall(r"^\s+(\w+):", block, re.M)) == set(themes.ICON_NAMES)


# ---- the CLI ---------------------------------------------------------------------------------


def test_cli_pack_check_unpack(tmp_path, capsys):
    from app.cli import main

    out = tmp_path / "sunset.ctheme"
    assert main(["theme", "pack", str(EXAMPLE), "-o", str(out)]) == 0
    assert main(["theme", "check", str(out)]) == 0
    assert "valid theme: 1 wallpaper(s), 2 icon(s)" in capsys.readouterr().out
    assert main(["theme", "unpack", str(out), str(tmp_path / "back.ctheme.d")]) == 0
    assert (tmp_path / "back.ctheme.d/icons/wallet.png").read_bytes() == (
        EXAMPLE / "icons/wallet.png"
    ).read_bytes()
    assert main(["theme", "unpack", str(out), str(tmp_path / "back.ctheme.d")]) == 1  # not empty


def test_cli_pack_refuses_stray_files_and_links(tmp_path, capsys):
    import shutil

    from app.cli import main

    folder = tmp_path / "mine.ctheme.d"
    shutil.copytree(EXAMPLE, folder)
    (folder / "notes.txt").write_text("my private notes")
    assert main(["theme", "pack", str(folder)]) == 1
    assert "notes.txt can't go in a bundle" in capsys.readouterr().err
    (folder / "notes.txt").unlink()
    (folder / "wallpapers/link.png").symlink_to(tmp_path / "elsewhere.png")
    assert main(["theme", "pack", str(folder)]) == 1
    assert "is a link" in capsys.readouterr().err


def test_cli_check_explains_problems(tmp_path, capsys):
    from app.cli import main

    bad = tmp_path / "bad.ctheme"
    bad.write_text(json.dumps(minimal(colors={**THEME["colors"], "accent": "red"})))
    assert main(["theme", "check", str(bad)]) == 1
    assert "colors.accent" in capsys.readouterr().err


def test_icon_pictures_are_reencoded_not_kept(logged_in):
    """A PNG icon carrying hidden text comes back as a clean re-encoded PNG."""
    from PIL import Image, PngImagePlugin

    meta = PngImagePlugin.PngInfo()
    meta.add_text("Comment", "hidden-payload-text")
    icon = io.BytesIO()
    Image.new("RGBA", (200, 200), (255, 0, 0, 255)).save(icon, "PNG", pnginfo=meta)
    assert b"hidden-payload-text" in icon.getvalue()
    r = upload(logged_in, zip_of({"theme.json": TJ, "icons/wallet.png": icon.getvalue()}))
    assert r.status_code == 201, r.text
    data = logged_in.get(f"/api/themes/{r.json()['id']}").json()
    png = base64.b64decode(data["icon_images"]["wallet"].split(",", 1)[1])
    assert b"hidden-payload-text" not in png
    assert Image.open(io.BytesIO(png)).size == (64, 64)  # shrunk to icon size


def test_unpack_never_writes_outside_its_folder(tmp_path):
    """Names are checked before anything is written. (The hostile name only reaches into this
    test's own temp folder, so even a broken check could not touch anything real.)"""
    out = tmp_path / "out"
    with pytest.raises(theme_bundle.BundleError):
        theme_bundle.unpack(zip_of({"theme.json": TJ, "../escape.txt": b"x"}), out)
    assert not (tmp_path / "escape.txt").exists()


def test_only_the_png_decoder_ever_sees_an_icon(monkeypatch):
    """Phase 3 review: an icon is opened by Pillow's PNG decoder only, never by guesswork."""
    import io

    from PIL import Image

    from app import themes

    seen = []
    real = Image.open

    def spy(fp, *a, **k):
        seen.append(k.get("formats"))
        return real(fp, *a, **k)

    monkeypatch.setattr(Image, "open", spy)
    buf = io.BytesIO()
    Image.new("RGBA", (32, 32), (10, 200, 10, 255)).save(buf, "PNG")
    themes.clean_icon(buf.getvalue())
    assert seen == [["PNG"]]
