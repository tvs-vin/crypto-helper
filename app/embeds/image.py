"""The preview image Discord (and other link previews) show: 1200x630 PNG, same toggles."""

import io
from functools import cache
from importlib import resources

from PIL import Image, ImageDraw, ImageFont

from app.embeds.page import change, fiat, group
from app.embeds.view import View

W, H = 1200, 630
PAD = 64


@cache
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = resources.files("app").joinpath(f"data/fonts/{name}.ttf")
    with resources.as_file(path) as p:
        return ImageFont.truetype(str(p), size)


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _fit(draw, text: str, f, width: int) -> str:
    if draw.textlength(text, font=f) <= width:
        return text
    while text and draw.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text + "…"


def _cells(r, view: View, c: dict) -> dict:
    cells = {}
    if r.amount is not None:
        cells["amount"] = (group(r.amount), c["text"])
    if r.price is not None:
        cells["price"] = (fiat(r.price, view.fiat), c["text"])
    if r.change is not None:
        text, cls = change(r.change)
        cells["change"] = (
            text,
            c["positive"] if cls == "up" else c["negative"] if cls else c["text"],
        )
    if r.value is not None:
        cells["value"] = (fiat(r.value, view.fiat), c["heading"])
    if r.percent is not None:
        cells["percent"] = (f"{r.percent}%", c["heading"])
    return cells


def render(view: View, theme: dict) -> bytes:
    c = {k: rgb(v) for k, v in theme["colors"].items() if v != "none"}
    img = Image.new("RGB", (W, H), c["desktop"])
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 6], fill=c["accent"])  # a thin accent band along the top

    # Brand mark (two stacked squares) and name, top right.
    x0 = W - PAD - 230
    d.rounded_rectangle(
        [x0, PAD - 6, x0 + 26, PAD + 20], radius=5, outline=c["border_strong"], width=3
    )
    d.rounded_rectangle([x0 + 11, PAD + 5, x0 + 37, PAD + 31], radius=5, fill=c["accent"])
    d.text(
        (x0 + 52, PAD - 2), "Crypto Helper", font=font("MonaSans-SemiBold", 28), fill=c["heading"]
    )

    y = PAD
    if view.title:
        d.text(
            (PAD, y - 8),
            _fit(d, view.title, font("MonaSans-SemiBold", 52), W - PAD * 2 - 260),
            font=font("MonaSans-SemiBold", 52),
            fill=c["heading"],
        )
        y += 72
    if view.total is not None:
        d.text(
            (PAD, y),
            fiat(view.total, view.fiat),
            font=font("MonaSans-SemiBold", 44),
            fill=c["heading"],
        )
        y += 64
    y += 16

    label_f = font("Inter-SemiBold", 30)
    cell_f = font("Inter-Regular", 28)
    rows = view.rows[: 8 if view.total is None else 6]
    row_h = 56
    order = ("amount", "price", "change", "value", "percent")
    table = [_cells(r, view, c) for r in rows]
    # Each column as wide as its widest entry, so numbers line up down the image.
    widths = {
        k: max((d.textlength(t[k][0], font=cell_f) for t in table if k in t), default=0)
        for k in order
    }
    for r, cells in zip(rows, table, strict=True):
        if y + row_h > H - PAD - 40:
            break
        xr = W - PAD
        for k in reversed(order):
            if not widths[k]:
                continue
            if k in cells:
                text, color = cells[k]
                d.text((xr - d.textlength(text, font=cell_f), y), text, font=cell_f, fill=color)
            xr -= widths[k] + 36
        lx = PAD
        if r.color:
            d.rounded_rectangle([lx, y + 12, lx + 14, y + 26], radius=3, fill=rgb(r.color))
            lx += 26
        d.text(
            (lx, y - 2),
            _fit(d, r.label, label_f, max(80, xr - lx - 20)),
            font=label_f,
            fill=c["heading"],
        )
        if r.percent is not None:
            bar_w = W - PAD * 2
            d.rounded_rectangle([PAD, y + 42, PAD + bar_w, y + 46], radius=2, fill=c["surface_alt"])
            frac = max(0.0, min(1.0, float(r.percent) / 100))
            if frac > 0:
                d.rounded_rectangle(
                    [PAD, y + 42, PAD + max(4, int(bar_w * frac)), y + 46],
                    radius=2,
                    fill=c["accent"],
                )
        y += row_h
    if len(view.rows) > len(rows):
        d.text((PAD, y), f"+ {len(view.rows) - len(rows)} more", font=cell_f, fill=c["text_muted"])

    foot = []
    if view.updated:
        foot.append(f"Updated {view.updated[:16].replace('T', ' ')} UTC")
    if view.attribution:
        foot.append(view.attribution)
    d.text(
        (PAD, H - PAD + 4),
        _fit(d, " · ".join(foot), font("Inter-Regular", 22), W - PAD * 2),
        font=font("Inter-Regular", 22),
        fill=c["text_muted"],
    )

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
