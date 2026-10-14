"""Wallet colors: a primary color (yours, or a stable default from the wallet's name) and
a secondary color that's either yours or derived from the primary by a chosen scheme."""

import colorsys
import hashlib
import re

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SCHEMES = ("analogous", "complementary", "triadic", "shade")
SECONDARY_MODES = ("auto", "custom")


def normalize_hex(value: str) -> str:
    if not HEX_RE.match(value):
        raise ValueError("Colors are #RRGGBB, e.g. #3b82f6.")
    return value.lower()


def _to_hex(h: float, lightness: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, min(max(lightness, 0.0), 1.0), min(max(s, 0.0), 1.0))
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _to_hls(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def default_primary(seed: str) -> str:
    """A pleasant, stable color from the wallet's name: same name, same color, every time."""
    digest = hashlib.sha256(seed.encode()).digest()
    hue = int.from_bytes(digest[:2], "big") / 65536
    return _to_hex(hue, 0.50, 0.60)


def derive_secondary(primary: str, scheme: str) -> str:
    h, lightness, s = _to_hls(primary)
    if scheme == "analogous":
        return _to_hex(h + 30 / 360, lightness, s)
    if scheme == "complementary":
        return _to_hex(h + 0.5, lightness, s)
    if scheme == "triadic":
        return _to_hex(h + 1 / 3, lightness, s)
    if scheme == "shade":
        # Same hue, clearly lighter or darker so the two stay distinguishable.
        return _to_hex(h, lightness - 0.22 if lightness > 0.5 else lightness + 0.22, s)
    raise ValueError(f"Unknown color scheme {scheme!r}; use one of {', '.join(SCHEMES)}.")


def resolve(name: str, primary: str | None, secondary: str | None, mode: str, scheme: str) -> dict:
    effective_primary = primary or default_primary(name)
    effective_secondary = (
        secondary if mode == "custom" and secondary else derive_secondary(effective_primary, scheme)
    )
    return {
        "primary": effective_primary,
        "secondary": effective_secondary,
        "primary_is_default": primary is None,
        "secondary_mode": mode,
        "scheme": scheme,
    }
