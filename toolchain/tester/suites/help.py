"""The Help window's pages (the wiki): read-only, for anyone signed in."""

from toolchain.tester.framework import check, expect, expect_status


@check("help", "401 anonymous; anyone signed in reads contents, pages and search")
def reading(ctx):
    expect_status(ctx.client().get("/api/help"), 401, "anonymous")
    name, _ = ctx.make_user([])
    c = ctx.as_user(name)
    sections = c.get("/api/help").json()["sections"]
    expect([s["title"] for s in sections][:2] == ["Start", "Guides"], f"{sections[:2]}")
    page = c.get("/api/help/page?id=guides/install-as-a-service")
    expect_status(page, 200, "a guide")
    expect(page.json()["blocks"], "an empty page")
    hits = c.get("/api/help/search?q=backup").json()["results"]
    expect(any(h["id"] == "guides/backups" for h in hits), f"search: {hits[:3]}")


@check("help", "only pages from the wiki's own list: paths are refused")
def only_known(ctx):
    c = ctx.admin
    for bad in ("../CLAUDE", "/etc/passwd", "guides/..%2F..%2Fapp%2Fconfig", "nope"):
        expect_status(c.get(f"/api/help/page?id={bad}"), 404, bad)
