"""The .ctheme format: a strict, data-only description of a theme.

A theme can only set known values (colors, fonts from a fixed list, a few bounded numbers).
It can never carry CSS, URLs or scripts, so a downloaded theme can't load anything from
elsewhere, track you, or break the page. The browser applies a theme through CSS variables;
app/web/js/theme.js repeats these checks before applying one.
"""

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

FORMAT = "crypto-helper-theme"
MAX_BYTES = 1024 * 1024  # room for PNG icons; colors alone are a few KB
BUILTIN = ("dark", "light", "terminal", "template")
FONTS = ("Inter", "Mona Sans", "JetBrains Mono", "system-ui", "sans-serif", "serif", "monospace")
COLOR_KEYS = (
    "desktop",
    "desktop_glow",
    "surface",
    "surface_alt",
    "titlebar",
    "titlebar_active",
    "taskbar",
    "border",
    "border_strong",
    "text",
    "text_muted",
    "heading",
    "accent",
    "accent_hover",
    "accent_text",
    "positive",
    "negative",
    "warning",
    "focus",
    "overlay",
    "selection",
)
# #RGB, #RRGGBB or #RRGGBBAA. Nothing else: no names, functions or url().
COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
OPTIONAL_NONE = {"desktop_glow"}  # may be "none"

# Icons a theme may replace (the keys of ICONS in app/web/js/dom.js; a test keeps them equal).
ICON_NAMES = (
    "minimize", "maximize", "restore", "close", "apps", "console", "terminal", "plus", "server",
    "appgrid", "tile", "floating", "logout", "settings", "wallet", "chart", "transfer", "users",
    "list", "shield", "bell", "help",
)  # fmt: skip
IconName = Literal[ICON_NAMES]
# SVG path data only: letters that are path commands, numbers, separators. No tags, no url(),
# nothing that could be anything but a shape (it's set as a path's "d" attribute).
PATH_RE = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE.,\s+-]{1,600}$")
DATA_PNG_RE = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/]+={0,2}$")
MAX_ICON_PNG = 16 * 1024
# A built-in wallpaper by name; inside a bundle also one of its files. "user:<id>" is only ever
# written by the server, after it has converted the bundle's file.
WALLPAPER_RE = re.compile(
    r"^(builtin:[a-z0-9-]{1,32}|user:\d{1,9}|wallpapers/[A-Za-z0-9._-]{1,60})$"
)

Font = Literal[
    "Inter", "Mona Sans", "JetBrains Mono", "system-ui", "sans-serif", "serif", "monospace"
]


def _check_color(cls, v, info):
    if info.field_name in OPTIONAL_NONE and v == "none":
        return v
    if not COLOR_RE.match(v):
        raise ValueError(f"{info.field_name} must be a hex color like #7545FC")
    return v


Colors = create_model(
    "Colors",
    __config__=ConfigDict(extra="forbid"),
    __validators__={"check_color": field_validator(*COLOR_KEYS)(_check_color)},
    **{key: (str, ...) for key in COLOR_KEYS},
)


class Fonts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: Font
    heading: Font
    mono: Font


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")

    radius: int = Field(ge=0, le=16)
    window_radius: int = Field(ge=0, le=20)
    border_width: int = Field(ge=0, le=3)


class Effects(BaseModel):
    model_config = ConfigDict(extra="forbid")

    glow: bool
    shadow: Literal["none", "soft", "strong"]


class Theme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["crypto-helper-theme"]
    version: Literal[1]
    name: str = Field(min_length=1, max_length=40)
    author: str = Field(default="", max_length=60)
    description: str = Field(default="", max_length=300)
    mode: Literal["dark", "light"]
    colors: Colors
    fonts: Fonts
    shape: Shape
    effects: Effects
    density: Literal["compact", "comfortable"]
    # Optional extras (bundles, milestone 8b). Any icon left out keeps the built-in one.
    icons: dict[IconName, list[str]] = Field(default_factory=dict)
    icon_images: dict[IconName, str] = Field(default_factory=dict)
    wallpaper: str | None = None

    @field_validator("icons")
    @classmethod
    def _paths(cls, v):
        for name, paths in v.items():
            if not 1 <= len(paths) <= 8 or not all(PATH_RE.match(p) for p in paths):
                raise ValueError(f"icon {name}: 1-8 SVG path strings (shape commands only)")
        return v

    @field_validator("icon_images")
    @classmethod
    def _pngs(cls, v):
        import base64

        for name, uri in v.items():
            if (
                not DATA_PNG_RE.match(uri)
                or len(base64.b64decode(uri.split(",", 1)[1])) > MAX_ICON_PNG
            ):
                raise ValueError(f"icon image {name}: a PNG data URI of at most 16 KB")
        return v

    @field_validator("wallpaper")
    @classmethod
    def _wallpaper(cls, v):
        if v is not None and not WALLPAPER_RE.match(v):
            raise ValueError("a built-in wallpaper (builtin:aurora) or a file in the bundle")
        return v

    @field_validator("name", "author", "description")
    @classmethod
    def _plain(cls, v):
        if any(ord(c) < 32 for c in v) or "<" in v or ">" in v:
            raise ValueError("text fields can't contain control characters or < >")
        return v.strip()


def parse(raw: bytes | str, *, bundle: bool = False) -> Theme:
    """Validate a .ctheme file's contents (or a bundle's theme.json). Raises ValueError with a
    readable message. A plain file may only name a built-in wallpaper."""
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Theme files are at most {MAX_BYTES // 1024} KB")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("That isn't a .ctheme file (it must be JSON)") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError('That isn\'t a .ctheme file (missing "format": "crypto-helper-theme")')
    theme = Theme(**data)
    wallpaper = theme.wallpaper or ""
    if wallpaper.startswith("user:") or (wallpaper.startswith("wallpapers/") and not bundle):
        raise ValueError("wallpaper: a built-in one here (builtin:aurora); files only in a bundle")
    return theme


def clean_icon(data: bytes) -> str:
    """Re-encode an icon picture as a small PNG data URI (64x64 at most)."""
    import base64
    import io

    from PIL import Image

    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 512 * 1024:
        raise ValueError("icons must be PNG files of at most 512 KB")
    try:
        im = Image.open(io.BytesIO(data))
        if im.size[0] * im.size[1] > 4_000_000:
            raise ValueError("that icon is too big")
        im.load()
        im = im.convert("RGBA")
        im.thumbnail((64, 64))
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)
    except ValueError:
        raise
    except Exception:
        raise ValueError("an icon couldn't be read as a PNG") from None
    if out.tell() > MAX_ICON_PNG:
        raise ValueError("an icon is too detailed (more than 16 KB at 64x64)")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()
