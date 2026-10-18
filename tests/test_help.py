"""10a: the Help window. The wiki parser, the API, and every wiki link resolving."""

import pytest
from fastapi.testclient import TestClient

from app import help as wiki
from tests.wallet_helpers import user_with

# ---- the parser ------------------------------------------------------------------------------


def test_inline_pieces():
    parts = wiki.inline(
        "Use `crypto-helper update`, see [Updating]({{ site.baseurl }}/guides/updating#roll-back) "
        "or [GitHub](https://github.com/x) — **bold** and *some* words.",
        "guides/x",
    )
    kinds = [p[0] for p in parts]
    assert kinds == ["text", "code", "text", "link", "text", "link", "text", "strong", "text",
                     "em", "text"]  # fmt: skip
    assert parts[3] == ["link", "Updating", {"page": "guides/updating", "anchor": "roll-back"}]
    assert parts[5] == ["link", "GitHub", {"url": "https://github.com/x"}]


@pytest.mark.parametrize("href", ["javascript:alert(1)", "data:text/html,x", "ftp://x/y", "x.md"])
def test_other_links_become_plain_text(href):
    assert wiki.inline(f"[click]({href})", "p") == [["text", "click"]]


def test_heading_ids_match_kramdown():
    assert wiki.anchor_id("3. Create the `super` account") == "create-the-super-account"
    assert wiki.anchor_id("Lost the phone *and* the codes") == "lost-the-phone-and-the-codes"
    assert wiki.anchor_id("9b: Discord") == "b-discord"


def test_blocks():
    md = """---
title: A page
---

# A page

First line
second line.

> **Careful.** Read this.

| Name | Shown |
|---|---|
| `a\\|b` | x \\| y |

1. Step one
   ```bash
   crypto-helper doctor
   ```
2. Step two
   - nested
     carried on

- loose
"""
    page = wiki.parse(md, "guides/a")
    assert page.title == "A page" and [b["t"] for b in page.blocks] == [
        "h", "p", "quote", "table", "ol", "ul"]  # fmt: skip
    assert page.blocks[1]["text"] == [["text", "First line second line."]]
    table = page.blocks[3]
    assert table["rows"] == [[[["code", "a|b"]], [["text", "x | y"]]]]
    steps = page.blocks[4]["items"]
    assert steps[0]["blocks"][0] == {"t": "code", "lang": "bash", "text": "crypto-helper doctor"}
    assert steps[1]["blocks"][0]["items"][0]["text"] == [["text", "nested carried on"]]
    assert "Step two" in page.text and "Careful" in page.text


def test_nothing_but_known_kinds(tmp_path):
    """Whatever a page holds, only these kinds reach the browser (it builds them as text)."""
    (tmp_path / "index.md").write_text("<script>alert(1)</script>\n\n<b>x</b> {% raw %}y\n")
    page = wiki.load(tmp_path)["index"]
    assert page.blocks == [{"t": "p", "text": [["text", "<script>alert(1)</script>"]]},
                           {"t": "p", "text": [["text", "<b>x</b> y"]]}]  # fmt: skip


def test_load_ignores_jekyll_files_and_odd_names(tmp_path):
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "ok-page.md").write_text("# Ok")
    (tmp_path / "guides" / "Bad Name.md").write_text("# no")
    (tmp_path / "_includes").mkdir()
    (tmp_path / "_includes" / "x.md").write_text("# no")
    assert list(wiki.load(tmp_path)) == ["guides/ok-page"]


# ---- the real wiki ---------------------------------------------------------------------------


def test_every_wiki_link_resolves():
    """Links between wiki pages (and their #anchors) all lead somewhere, here and on Pages."""
    pages = wiki.load()
    broken = []
    for p in pages.values():
        for label, target in wiki._links(p.blocks):
            if "page" not in target:
                continue
            dest = pages.get(target["page"])
            anchors = {h[0] for h in dest.headings} if dest else set()
            if dest is None or (target["anchor"] and target["anchor"] not in anchors):
                broken.append(f"{p.id}: [{label}] -> {target}")
    assert not broken, "\n".join(broken)


def test_contents_lists_every_page():
    pages = wiki.load()
    listed = {e["id"] for s in wiki.contents(pages) for e in s["pages"]}
    assert listed == set(pages)


# ---- the API ---------------------------------------------------------------------------------


def test_needs_a_session(app):
    c = TestClient(app)
    assert c.get("/api/help").status_code == 401
    assert c.get("/api/help/page?id=index").status_code == 401


def test_anyone_signed_in_reads_it(logged_in, app):
    bob = user_with(app, logged_in, "bob", [])  # no permissions at all
    sections = bob.get("/api/help").json()["sections"]
    assert [s["title"] for s in sections] == ["Start", "Guides", "Reference", "Project", "Tools"]
    page = bob.get("/api/help/page", params={"id": "guides/notifications"}).json()
    assert page["title"] == "Notifications" and page["blocks"][0]["t"] == "h"
    hits = bob.get("/api/help/search", params={"q": "discord webhook"}).json()["results"]
    assert hits and any(h["id"] == "guides/notifications" for h in hits)
    assert "help" in bob.get("/api/auth/me").json()["apps"]


@pytest.mark.parametrize(
    "page_id", ["../CLAUDE", "/etc/passwd", "guides/../../app/config", "guides/nope", "INDEX"]
)
def test_only_known_pages(logged_in, page_id):
    assert logged_in.get("/api/help/page", params={"id": page_id}).status_code == 404


def test_every_window_help_button_leads_somewhere():
    """Each window's "?" opens a page (and heading) that exists."""
    import re
    from pathlib import Path

    js = (Path(wiki.__file__).parent / "web/js/panels.js").read_text()
    guides = re.findall(r'guide: "([^"]+)"', js)
    assert len(guides) >= 10
    pages = wiki.load()
    for g in guides:
        page, _, anchor = g.partition("#")
        assert page in pages, g
        assert not anchor or anchor in {h[0] for h in pages[page].headings}, g
