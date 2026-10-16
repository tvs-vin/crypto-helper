"""The web app's files and how they're served (the browser tests are in tests/ui)."""

import json
import re
from pathlib import Path

import pytest

from app import themes
from tests.conftest import H

WEB = Path(__file__).resolve().parents[1] / "app" / "web"


def test_index_is_served_with_the_strict_policy(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert r.headers["cache-control"] == "no-cache"


def test_index_has_no_inline_script_or_style():
    html = (WEB / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)  # every script has src=
    assert "<style" not in html and " style=" not in html and "onclick=" not in html.lower()


def test_every_referenced_file_exists(client):
    html = (WEB / "index.html").read_text()
    for path in re.findall(r'(?:href|src)="(/static/[^"]+)"', html):
        assert client.get(path).status_code == 200, path
    for js in WEB.glob("js/**/*.js"):
        for imp in re.findall(r'from "(\.{1,2}/[^"]+)"', js.read_text()):
            assert (js.parent / imp).resolve().exists(), f"{js.name} imports missing {imp}"


def test_no_markup_injection_sinks_in_the_js():
    """All dynamic text goes through textContent; these APIs would allow markup."""
    for js in WEB.glob("js/**/*.js"):
        # Strip comments: "never innerHTML" in a comment is fine.
        src = re.sub(r"/\*.*?\*/|//[^\n]*", "", js.read_text(), flags=re.S)
        for sink in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
            "eval(",
            "new Function",
        ):
            assert sink not in src, f"{js.name} uses {sink}"


def test_no_raw_replace_children():
    """Regression: replaceChildren(x, null) shows the text "null" ("5 walletsnull").
    Use dom.js fill(), which skips empty slots."""
    for js in WEB.glob("js/**/*.js"):
        if js.name != "dom.js":
            assert ".replaceChildren(" not in js.read_text(), js.name


def test_no_external_urls_in_css_or_js():
    for f in [*WEB.glob("css/*.css"), *WEB.glob("js/**/*.js")]:
        # Allowed: the SVG namespace, and placeholders on the reserved example.com domain.
        pattern = r"https?://(?!www\.w3\.org/2000/svg|[a-z0-9.-]*example\.com\b)"
        assert not re.search(pattern, f.read_text()), f.name


def test_static_files_revalidate_and_traversal_is_blocked(client):
    r = client.get("/static/js/main.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.headers["etag"]
    assert client.get("/static/../app/config.py").status_code == 404
    assert client.get("/static/%2e%2e/%2e%2e/app/config.py").status_code == 404


def test_fonts_are_present_with_their_licences():
    for name in ("inter", "monasans", "jetbrainsmono"):
        assert (WEB / "fonts" / f"{name}.woff2").read_bytes()[:4] == b"wOF2"
        assert "SIL OPEN FONT LICENSE" in (WEB / "fonts" / f"{name}-OFL.txt").read_text()


# ---- themes ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", themes.BUILTIN)
def test_builtin_themes_are_valid_and_served_as_json(client, name):
    t = themes.parse((WEB / "themes" / f"{name}.ctheme").read_text())
    assert t.format == "crypto-helper-theme"
    r = client.get(f"/static/themes/{name}.ctheme")
    assert r.headers["content-type"].startswith("application/json")


def test_template_lists_every_key():
    template = json.loads((WEB / "themes" / "template.ctheme").read_text())
    assert set(template["colors"]) == set(themes.COLOR_KEYS)
    assert set(template) == set(themes.Theme.model_fields)


def good():
    return json.loads((WEB / "themes" / "dark.ctheme").read_text())


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda t: t["colors"].update(accent="url(https://evil.example/x.png)"), "hex color"),
        (lambda t: t["colors"].update(accent="red; background: url(x)"), "hex color"),
        (lambda t: t["colors"].update(accent="expression(alert(1))"), "hex color"),
        (lambda t: t["fonts"].update(body="Comic Sans', url(x)"), "fonts.body"),
        (lambda t: t.update(css="body{display:none}"), "Extra inputs"),
        (lambda t: t["colors"].update(sneaky="#000000"), "Extra inputs"),
        (lambda t: t.update(name="<img src=x onerror=alert(1)>"), "< >"),
        (lambda t: t["shape"].update(radius=500), "radius"),
        (lambda t: t.update(version=2), "version"),
        (lambda t: t["colors"].pop("accent"), "accent"),
    ],
)
def test_theme_parser_refuses_anything_but_plain_values(mutate, fragment):
    t = good()
    mutate(t)
    with pytest.raises(ValueError, match=re.escape(fragment)):
        themes.parse(json.dumps(t))


def test_theme_parser_size_and_format():
    with pytest.raises(ValueError, match="at most"):
        themes.parse(" " * (themes.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="must be JSON"):
        themes.parse("theme: dark")
    with pytest.raises(ValueError, match="crypto-helper-theme"):
        themes.parse("{}")


# ---- the layout preferences the desktop saves --------------------------------------------


def test_layout_modes_and_window_flags_round_trip(logged_in):
    layout = {
        "mode": "tiled",
        "tiling": "grid",
        "windows": [
            {
                "panel": "wallets",
                "x": 8,
                "y": 8,
                "w": 700,
                "h": 400,
                "open": True,
                "minimized": True,
                "maximized": False,
                "z": 1,
            }
        ],
    }
    r = logged_in.patch(
        "/api/me/preferences", json={"layout": layout, "theme": "template"}, headers=H
    )
    assert r.status_code == 200
    # The server fills in each window's id (its first window: the app's name) and state.
    expected = {**layout, "windows": [{**layout["windows"][0], "id": "wallets", "state": {}}]}
    assert r.json()["layout"] == expected and r.json()["theme"] == "template"
    bad = {**layout, "mode": "spiral"}
    assert (
        logged_in.patch("/api/me/preferences", json={"layout": bad}, headers=H).status_code == 422
    )
