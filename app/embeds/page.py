"""The embed page: server-built HTML, no JavaScript, every value escaped."""

from html import escape

from app.embeds.view import View

SYMBOLS = {"usd": "$", "eur": "€", "gbp": "£", "jpy": "¥", "cad": "CA$", "aud": "A$"}


def group(d: str) -> str:
    neg = d.startswith("-")
    d = d.lstrip("-")
    whole, _, frac = d.partition(".")
    whole = f"{int(whole):,}" if whole.isdigit() else whole
    return ("-" if neg else "") + whole + (f".{frac}" if frac else "")


def fiat(v: str, cur: str) -> str:
    """ "-1234.5" -> "-$1,234.50" (text only: a one-digit fraction gets its cents)."""
    neg, body = v.startswith("-"), v.lstrip("-")
    whole, dot, frac = body.partition(".")
    if dot and len(frac) == 1:
        body += "0"
    return f"{'-' if neg else ''}{SYMBOLS.get(cur, '')}{group(body)}"


def change(c: str) -> tuple[str, str]:
    n = float(c)  # a percentage for display, not money
    return (f"{'+' if n > 0 else ''}{n:.2f}%", "up" if n > 0 else "down" if n < 0 else "")


def _row(r, v: View) -> str:
    cells = []
    if r.amount is not None:
        cells.append(f'<span class="amount">{escape(group(r.amount))}</span>')
    if r.price is not None:
        cells.append(f'<span class="price">{escape(fiat(r.price, v.fiat))}</span>')
    if r.change is not None:
        text, cls = change(r.change)
        cells.append(f'<span class="change {cls}">{escape(text)}</span>')
    if r.value is not None:
        cells.append(f'<span class="value">{escape(fiat(r.value, v.fiat))}</span>')
    bar = ""
    if r.percent is not None:
        pct = max(0.0, min(100.0, float(r.percent)))
        cells.append(f'<span class="pct">{escape(r.percent)}%</span>')
        bar = f'<span class="bar"><span class="fill w{round(pct)}"></span></span>'
    dot = f'<span class="dot c{escape(r.color[1:])}"></span>' if r.color else ""
    tags = "".join(f'<span class="tag">{escape(t)}</span>' for t in r.tags)
    sub = f'<span class="sub">{escape(r.sub)}</span>' if r.sub else ""
    head = (
        f'<div class="row"><span class="label">{dot}{escape(r.label)}{sub}</span>'
        f'<span class="cells">{"".join(cells)}</span></div>{bar}'
    )
    kids = "".join(_row(c, v) for c in r.children)
    if r.children or r.tags:
        return (
            f'<section class="card">{head}'
            f"{f'<div class=tags>{tags}</div>' if tags else ''}"
            f"{f'<div class=kids>{kids}</div>' if kids else ''}</section>"
        )
    return f'<div class="item">{head}</div>'


def render(v: View, token: str, base_url: str, refresh_seconds: int = 300) -> str:
    title = v.title or "Crypto Helper"
    image = f"{base_url}/embed/{token}.png"
    rows = "".join(_row(r, v) for r in v.rows) or '<p class="empty">Nothing to show.</p>'
    total = f'<p class="total">{escape(fiat(v.total, v.fiat))}</p>' if v.total is not None else ""
    foot = []
    if v.updated:
        shown = escape(v.updated[:16]).replace("T", " ")
        foot.append(f'<time datetime="{escape(v.updated)}Z">Updated {shown} UTC</time>')
    if v.stale:
        foot.append("<span class=stale>prices may be out of date</span>")
    if v.attribution:
        foot.append(f"<span>{escape(v.attribution)}</span>")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="referrer" content="no-referrer">
<meta http-equiv="refresh" content="{int(refresh_seconds)}">
<title>{escape(title)}</title>
<meta property="og:type" content="website">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(v.summary)}">
<meta property="og:image" content="{escape(image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="/embed-assets/embed.css">
<link rel="stylesheet" href="/embed/{escape(token)}.css">
</head>
<body class="kind-{escape(v.kind)}">
<main>
{f"<h1>{escape(v.title)}</h1>" if v.title else ""}
{total}
<div class="rows">{rows}</div>
<footer>{" · ".join(foot)}</footer>
</main>
</body>
</html>
"""


def css(theme: dict, view: View) -> str:
    """Per-embed colors. Every value was validated as a hex color by the theme schema."""
    c = theme["colors"]
    lines = [":root {"]
    for key in (
        "desktop",
        "surface",
        "surface_alt",
        "border",
        "border_strong",
        "text",
        "text_muted",
        "heading",
        "accent",
        "positive",
        "negative",
        "warning",
    ):
        lines.append(f"  --{key.replace('_', '-')}: {c[key]};")
    lines.append("}")
    every = [*view.rows, *(kid for row in view.rows for kid in row.children)]
    for item in every:
        if item.color:
            lines.append(f".c{item.color[1:]} {{ background: {item.color}; }}")
    return "\n".join(lines) + "\n"
