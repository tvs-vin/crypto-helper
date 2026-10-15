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
MAX_BYTES = 32 * 1024
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

    @field_validator("name", "author", "description")
    @classmethod
    def _plain(cls, v):
        if any(ord(c) < 32 for c in v) or "<" in v or ">" in v:
            raise ValueError("text fields can't contain control characters or < >")
        return v.strip()


def parse(raw: bytes | str) -> Theme:
    """Validate a .ctheme file's contents. Raises ValueError with a readable message."""
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Theme files are at most {MAX_BYTES // 1024} KB")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("That isn't a .ctheme file (it must be JSON)") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError('That isn\'t a .ctheme file (missing "format": "crypto-helper-theme")')
    return Theme(**data)
