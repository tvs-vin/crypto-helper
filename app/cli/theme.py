"""`crypto-helper theme pack|unpack|check`: make and inspect theme bundles (.ctheme).

Nothing here needs the server or root: it runs the same checks the server does, so a bundle
that passes `check` will upload (wallpapers are converted on upload, which `check` also does).
"""

from pathlib import Path

from app.cli.common import CliError, ok, step


def _theme_from(data: bytes):
    from app import theme_bundle, themes
    from app.routers.themes import _with_clean_icons

    if theme_bundle.is_bundle(data):
        b = theme_bundle.read(data)
        theme = themes.parse(b.theme_json, bundle=True)
    else:
        b = theme_bundle.Bundle(theme_json=data)
        theme = themes.parse(data)
    stored = _with_clean_icons(theme, b.icons)
    if (theme.wallpaper or "").startswith("wallpapers/") and theme.wallpaper not in b.wallpapers:
        raise ValueError(f"wallpaper: {theme.wallpaper} isn't in the bundle")
    return theme, b, stored


def _explain(e: Exception) -> CliError:
    from pydantic import ValidationError

    if isinstance(e, ValidationError):
        lines = [f"  {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        return CliError("The theme has problems:\n" + "\n".join(lines[:30]))
    return CliError(str(e))


def check(path: Path) -> int:
    from pydantic import ValidationError

    from app import theme_bundle
    from app import wallpapers as wp

    path = Path(path)
    if not path.exists():
        raise CliError(f"{path} doesn't exist.")
    try:
        data = theme_bundle.pack(path) if path.is_dir() else path.read_bytes()
        theme, b, stored = _theme_from(data)
        for name, content in b.wallpapers.items():
            step(f"Converting {name} (as the server would)")
            p = wp.process(content)
            print(f"    {p.kind}, {p.width}x{p.height}, {len(p.data) // 1024} KB")
    except (ValidationError, ValueError, wp.WallpaperError) as e:
        raise _explain(e) from None
    icons = len(stored.get("icon_images") or {}) + len(stored.get("icons") or {})
    print(
        ok(f"“{theme.name}” is a valid theme: {len(b.wallpapers)} wallpaper(s), {icons} icon(s).")
    )
    return 0


def pack(folder: Path, out: Path | None) -> int:
    from pydantic import ValidationError

    from app import theme_bundle

    folder = Path(folder)
    if not folder.is_dir():
        raise CliError(f"{folder} isn't a folder (expected something like my-theme.ctheme.d).")
    out = (
        Path(out)
        if out
        else folder.with_name(folder.name.removesuffix(".d").removesuffix(".ctheme") + ".ctheme")
    )
    if out.exists():
        raise CliError(f"{out} already exists; pick another name with -o.")
    try:
        data = theme_bundle.pack(folder)
        theme, b, _ = _theme_from(data)
    except (ValidationError, ValueError) as e:
        raise _explain(e) from None
    out.write_bytes(data)
    size = f"{len(data) // 1024} KB, {len(b.wallpapers)} wallpaper(s)"
    print(ok(f"Packed “{theme.name}” into {out} ({size})."))
    print("  Check the wallpapers convert too: crypto-helper theme check", out)
    return 0


def unpack(file: Path, folder: Path | None) -> int:
    from app import theme_bundle

    file = Path(file)
    data = file.read_bytes()
    if not theme_bundle.is_bundle(data):
        raise CliError(f"{file} is a plain theme (JSON), not a bundle: edit it directly.")
    folder = Path(folder) if folder else file.with_name(file.stem + ".ctheme.d")
    try:
        theme_bundle.unpack(data, folder)
    except ValueError as e:
        raise CliError(str(e)) from None
    print(ok(f"Unpacked into {folder}"))
    return 0
