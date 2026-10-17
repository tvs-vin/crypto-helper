"""Themes: a plain .ctheme and a bundle (wallpaper + icons) uploaded by throwaway users, a
hostile bundle refused, and download. Deletes what it uploads."""

import io
import json
import zipfile

from toolchain.tester.framework import check, expect, expect_status


def _theme(ctx) -> dict:
    t = ctx.admin.get("/static/themes/dark.ctheme").json()
    return {**t, "name": "t_theme", "wallpaper": "builtin:dusk"}


def _post(c, data: bytes):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"{c.base_url}/api/themes/upload", data=data, method="POST",
        headers={"Content-Type": "application/octet-stream", "X-Requested-With": "fetch"},
    )  # fmt: skip
    try:
        with c.opener.open(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _bundle(theme: dict, extra: dict | None = None) -> bytes:
    from PIL import Image

    pic = io.BytesIO()
    Image.new("RGB", (640, 360), (180, 90, 60)).save(pic, "PNG")
    icon = io.BytesIO()
    Image.new("RGBA", (32, 32), (240, 140, 80, 255)).save(icon, "PNG")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("theme.json", json.dumps({**theme, "wallpaper": "wallpapers/sky.png"}))
        zf.writestr("wallpapers/sky.png", pic.getvalue())
        zf.writestr("icons/wallet.png", icon.getvalue())
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return out.getvalue()


@check("themes", "a plain .ctheme with a built-in wallpaper")
def plain(ctx):
    name, _ = ctx.make_user([])
    c = ctx.as_user(name)
    status, t = _post(c, json.dumps(_theme(ctx)).encode())
    expect(status == 201 and t["wallpaper"] == "builtin:dusk", f"{status} {t}")
    expect_status(c.delete(f"/api/themes/{t['id']}"), 204, "delete")


@check("themes", "a bundle: wallpaper converted, icon re-encoded, download, delete")
def bundle(ctx):
    name, _ = ctx.make_user([])
    c = ctx.as_user(name)
    status, t = _post(c, _bundle(_theme(ctx)))
    expect(status == 201 and t["bundle"] and t["icons"] == 1, f"{status} {t}")
    wid = t["wallpaper"].removeprefix("user:")
    f = c.get(f"/api/wallpapers/{wid}/file")
    expect_status(f, 200, "theme wallpaper")
    expect(f.headers.get("content-type") == "image/webp", "wallpaper not converted")
    d = c.get(f"/api/themes/{t['id']}/bundle")
    expect_status(d, 200, "download")
    expect(d.headers.get("content-type") == "application/zip", "download isn't a zip")
    expect_status(c.delete(f"/api/themes/{t['id']}"), 204, "delete")
    expect_status(c.get(f"/api/wallpapers/{wid}/file"), 404, "wallpaper gone with its theme")


@check("themes", "a bundle with a stray file or a path out of it is refused")
def hostile(ctx):
    name, _ = ctx.make_user([])
    c = ctx.as_user(name)
    for extra in ({"index.html": b"<script>"}, {"../escape.txt": b"x"}):
        status, body = _post(c, _bundle(_theme(ctx), extra))
        expect(status == 422 and "may only contain" in body.get("detail", ""), f"{extra}: {status}")
