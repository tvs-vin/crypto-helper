"""Embed links: the management API on the main server and, when the embed server is on,
the links themselves. Everything is made by throwaway t_* users (deleted with them)."""

from toolchain.tester.client import Client
from toolchain.tester.framework import Skip, check, expect, expect_status

PERMS = ["embeds.create", "wallets.view", "prices.view"]


def _maker(ctx):
    name, _ = ctx.make_user(PERMS)
    return ctx.as_user(name)


def _embed_client(ctx, c) -> tuple[Client, str]:
    meta = c.get("/api/embeds/meta").json()
    if not meta["enabled"]:
        raise Skip("the embed server is off (crypto-helper embed enable)")
    server = Client(meta["base_url"])
    try:
        server.get("/embed-assets/embed.css")
    except OSError as e:
        raise Skip(f"embed server not reachable at {meta['base_url']}: {e}") from None
    return server, meta["base_url"]


def _path(url: str, base: str) -> str:
    return url.removeprefix(base)


@check("embeds", "401 anonymous, 403 without embeds.create")
def access(ctx):
    expect_status(ctx.client().get("/api/embeds"), 401, "anonymous")
    name, _ = ctx.make_user(["wallets.view"])
    c = ctx.as_user(name)
    expect_status(c.get("/api/embeds"), 403, "list without embeds.create")
    expect_status(c.post("/api/embeds", {"name": "x", "kind": "prices"}), 403, "create")


@check("embeds", "create, edit, new link, delete; amounts and values start off")
def lifecycle(ctx):
    c = _maker(ctx)
    meta = c.get("/api/embeds/meta").json()
    expect(
        meta["items"]["amounts"]["sensitive"] and not meta["items"]["amounts"]["default"],
        "amounts should be sensitive and off by default",
    )
    r = c.post("/api/embeds", {"name": "t_embed", "kind": "portfolio"})
    expect_status(r, 201, "create")
    e = r.json()
    expect(not e["options"]["items"]["amounts"] and not e["options"]["items"]["values"],
           "amounts/values on by default")  # fmt: skip
    expect("/embed/" in e["url"] and e["image_url"] == e["url"] + ".png", f"url {e['url']}")
    r = c.patch(f"/api/embeds/{e['id']}", {"name": "t_embed2", "enabled": False})
    expect_status(r, 200, "patch")
    expect(r.json()["name"] == "t_embed2" and not r.json()["enabled"], "patch didn't apply")
    r = c.post(f"/api/embeds/{e['id']}/rotate")
    expect_status(r, 200, "rotate")
    expect(r.json()["url"] != e["url"], "rotate kept the same link")
    expect_status(c.delete(f"/api/embeds/{e['id']}"), 204, "delete")
    expect(c.get("/api/embeds").json() == [], "deleted embed still listed")


@check("embeds", "others can't see or change your embeds")
def private(ctx):
    a, b = _maker(ctx), _maker(ctx)
    e = a.post("/api/embeds", {"name": "t_mine", "kind": "prices"}).json()
    expect(b.get("/api/embeds").json() == [], "another user's embed is listed")
    expect_status(b.patch(f"/api/embeds/{e['id']}", {"enabled": False}), 404, "patch other's")
    expect_status(b.delete(f"/api/embeds/{e['id']}"), 404, "delete other's")
    expect_status(b.get(f"/api/embeds/{e['id']}/preview.png"), 404, "preview other's")


@check("embeds", "bad options are refused")
def validation(ctx):
    c = _maker(ctx)
    for options in (
        {"items": {"secret_keys": True}},
        {"allowed_origins": ["javascript:alert(1)"]},
        {"theme": "../../etc/passwd"},
        {"refresh_seconds": 1},
        {"surprise": 1},
    ):
        r = c.post("/api/embeds", {"name": "t_bad", "kind": "prices", "options": options})
        expect_status(r, 422, f"options {options}")
    expect_status(c.post("/api/embeds", {"name": "t_bad", "kind": "secrets"}), 422, "kind")


@check("embeds", "preview image")
def preview(ctx):
    c = _maker(ctx)
    e = c.post("/api/embeds", {"name": "t_img", "kind": "prices"}).json()
    r = c.get(f"/api/embeds/{e['id']}/preview.png")
    expect_status(r, 200, "preview")
    expect(r.headers.get("content-type") == "image/png", "not a PNG")


@check("embeds", "embed server: page, image, headers; off and old links 404")
def served(ctx):
    c = _maker(ctx)
    srv, base = _embed_client(ctx, c)
    e = c.post("/api/embeds", {"name": "t_live", "kind": "prices"}).json()
    page = srv.get(_path(e["url"], base))
    expect_status(page, 200, "embed page")
    expect("<script" not in page.text.lower(), "embed page has a script")
    csp = page.headers.get("content-security-policy", "")
    expect("default-src 'none'" in csp and "frame-ancestors 'none'" in csp, f"CSP {csp}")
    expect(page.headers.get("x-frame-options") == "DENY", "framing not refused")
    expect('property="og:image"' in page.text, "no preview image for Discord")
    expect_status(srv.get(_path(e["image_url"], base)), 200, "embed image")
    expect_status(srv.post(_path(e["url"], base), {}, csrf=False), 405, "POST to the embed server")
    expect_status(srv.get("/api/auth/me"), 404, "the app's API on the embed server")
    c.patch(f"/api/embeds/{e['id']}", {"enabled": False})
    expect_status(srv.get(_path(e["url"], base)), 404, "switched-off embed")
    c.patch(f"/api/embeds/{e['id']}", {"enabled": True})
    new = c.post(f"/api/embeds/{e['id']}/rotate").json()
    expect_status(srv.get(_path(e["url"], base)), 404, "old link after a new one")
    expect_status(srv.get(_path(new["url"], base)), 200, "new link")


@check("embeds", "embed server: only listed sites may frame it")
def framing(ctx):
    c = _maker(ctx)
    srv, base = _embed_client(ctx, c)
    opts = {"allowed_origins": ["https://blog.example.com"]}
    e = c.post("/api/embeds", {"name": "t_frame", "kind": "prices", "options": opts}).json()
    r = srv.get(_path(e["url"], base))
    csp = r.headers.get("content-security-policy", "")
    expect("frame-ancestors https://blog.example.com" in csp, f"CSP {csp}")
    expect("x-frame-options" not in r.headers, "X-Frame-Options would block the listed site")
