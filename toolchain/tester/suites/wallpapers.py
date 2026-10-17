"""Wallpapers: the built-in set, an upload by a throwaway user (checked, converted, private),
and refusing a file that isn't a picture. Deletes what it uploads."""

import io
import json
import urllib.error
import urllib.request

from toolchain.tester.framework import check, expect, expect_status


def _png() -> bytes:
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (640, 360), (20, 80, 120)).save(b, "PNG")
    return b.getvalue()


def _upload(c, data: bytes, name: str):
    req = urllib.request.Request(
        f"{c.base_url}/api/wallpapers?name={name}", data=data, method="POST",
        headers={"Content-Type": "application/octet-stream", "X-Requested-With": "fetch"},
    )  # fmt: skip
    try:
        with c.opener.open(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


@check("wallpapers", "the built-in set is listed and served")
def builtins(ctx):
    data = ctx.admin.get("/api/wallpapers").json()
    keys = [w["key"] for w in data["builtin"]]
    expect("builtin:aurora" in keys and "builtin:drift" in keys, f"built-ins {keys}")
    for w in data["builtin"]:
        expect_status(ctx.admin.get(w["url"]), 200, w["url"])


@check("wallpapers", "an upload is converted, private, and deleted by its owner")
def upload(ctx):
    name, _ = ctx.make_user([])
    c = ctx.as_user(name)
    status, w = _upload(c, _png(), "t_wall")
    expect(status == 201, f"upload: {status} {w}")
    f = c.get(w["url"])
    expect_status(f, 200, "file")
    expect(f.headers.get("content-type") == "image/webp", "not converted to WebP")
    other, _ = ctx.make_user([])
    expect_status(ctx.as_user(other).get(w["url"]), 404, "another user")
    expect_status(c.delete(f"/api/wallpapers/{w['id']}"), 204, "delete")


@check("wallpapers", "a file that isn't a picture is refused")
def refused(ctx):
    name, _ = ctx.make_user([])
    status, body = _upload(ctx.as_user(name), b"not a picture at all" * 8, "t_bad")
    expect(status == 422 and "Not a picture" in body.get("detail", ""), f"{status} {body}")
