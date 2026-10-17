"""Theme bundles: a .ctheme that's a zip of theme.json plus wallpapers/ and icons/.

    my-theme.ctheme.d/          the editable folder ("crypto-helper theme pack" zips it)
      theme.json                the colours etc., exactly like a plain .ctheme
      wallpapers/<name>.<ext>   up to 5 pictures, animations or videos
      icons/<icon name>.png     PNG icons named after the icons they replace

Zips are hostile until proven otherwise. Before anything is unpacked: only the names above
(no paths out of the bundle, no links, no encryption), at most 60 files, sizes and compression
ratios checked against limits, and each file read only up to its declared size. Everything
inside is then checked like an upload (theme rules, wallpaper conversion, icon re-encoding).
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ZIP_MAGIC = b"PK\x03\x04"
MAX_BUNDLE = 80 * 1024 * 1024
MAX_FILES = 60
MAX_WALLPAPERS = 5
MAX_UNPACKED = 200 * 1024 * 1024
MAX_FILE = 60 * 1024 * 1024
MAX_RATIO = 200  # unpacked/packed, for anything over 1 MB: zip bombs have huge ratios
NAME_RE = re.compile(
    r"^(theme\.json|wallpapers/[A-Za-z0-9._-]{1,60}\.(png|jpe?g|webp|gif|mp4|webm)"
    r"|icons/[a-z]{1,32}\.png)$"
)
FOLDERS = {"wallpapers/", "icons/"}


class BundleError(ValueError):
    """A bundle we won't open; the message is safe to show."""


@dataclass
class Bundle:
    theme_json: bytes = b""
    wallpapers: dict[str, bytes] = field(default_factory=dict)  # "wallpapers/x.webp" -> bytes
    icons: dict[str, bytes] = field(default_factory=dict)  # icon name -> PNG bytes


def is_bundle(data: bytes) -> bool:
    return data[:4] == ZIP_MAGIC


def read(data: bytes) -> Bundle:
    if len(data) > MAX_BUNDLE:
        raise BundleError(f"Bundles can be at most {MAX_BUNDLE // 1024 // 1024} MB.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise BundleError("That file isn't a theme bundle (it's not a readable zip).") from None
    if len(infos) > MAX_FILES:
        raise BundleError(f"Bundles can hold at most {MAX_FILES} files.")
    b, total, seen = Bundle(), 0, set()
    for info in infos:
        name = info.filename
        if name in FOLDERS:  # plain folder entries
            continue
        if not NAME_RE.match(name):
            raise BundleError(
                "Bundles may only contain theme.json, wallpapers/ and icons/<icon>.png "
                f"(found {name[:80]!r})."
            )
        if name in seen:
            raise BundleError("A file appears twice in the bundle.")
        seen.add(name)
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise BundleError("Bundles can't contain links.")
        if info.flag_bits & 0x1:
            raise BundleError("Bundles can't be encrypted.")
        if info.file_size > MAX_FILE:
            raise BundleError(f"{name} is too big.")
        total += info.file_size
        if total > MAX_UNPACKED:
            raise BundleError("The bundle unpacks to too much data.")
        if info.file_size > 1024 * 1024 and info.file_size > MAX_RATIO * max(1, info.compress_size):
            raise BundleError(f"{name} is compressed suspiciously well; refusing to unpack it.")
        try:
            with zf.open(info) as f:
                content = f.read(info.file_size + 1)  # never more than it claims
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
            raise BundleError(f"{name} couldn't be read.") from None
        if len(content) != info.file_size:
            raise BundleError(f"{name} isn't the size the bundle says.")
        if name == "theme.json":
            b.theme_json = content
        elif name.startswith("wallpapers/"):
            b.wallpapers[name] = content
        else:
            b.icons[name.removeprefix("icons/").removesuffix(".png")] = content
    if not b.theme_json:
        raise BundleError("The bundle has no theme.json.")
    if len(b.wallpapers) > MAX_WALLPAPERS:
        raise BundleError(f"Bundles can hold at most {MAX_WALLPAPERS} wallpapers.")
    return b


def _write(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name in sorted(files, key=lambda n: (n != "theme.json", n)):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            # Pictures and videos are compressed already.
            info.compress_type = (
                zipfile.ZIP_STORED if name.startswith("wallpapers/") else zipfile.ZIP_DEFLATED
            )
            zf.writestr(info, files[name])
    return out.getvalue()


def pack(folder: Path) -> bytes:
    """Zip a .ctheme.d folder. Only the files a bundle may hold; anything else is an error
    (so nothing private gets packed by accident)."""
    folder = Path(folder)
    files = {}
    for path in sorted(folder.rglob("*")):
        if path.is_dir():
            continue
        if path.is_symlink():
            raise BundleError(f"{path.relative_to(folder)} is a link; bundles can't hold links.")
        rel = path.relative_to(folder).as_posix()
        if not NAME_RE.match(rel):
            raise BundleError(
                f"{rel} can't go in a bundle: only theme.json, wallpapers/<file> "
                "(png, jpg, webp, gif, mp4, webm) and icons/<icon name>.png."
            )
        files[rel] = path.read_bytes()
    if "theme.json" not in files:
        raise BundleError(f"{folder} has no theme.json.")
    data = _write(files)
    read(data)  # what we make must pass our own checks
    return data


def unpack(data: bytes, folder: Path) -> None:
    b = read(data)
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise BundleError(f"{folder} isn't empty.")
    (folder / "wallpapers").mkdir(parents=True, exist_ok=True)
    (folder / "icons").mkdir(exist_ok=True)
    (folder / "theme.json").write_bytes(b.theme_json)
    for name, content in b.wallpapers.items():
        (folder / name).write_bytes(content)
    for name, content in b.icons.items():
        (folder / "icons" / f"{name}.png").write_bytes(content)


def build(theme: dict, wallpapers: dict[str, bytes], icons: dict[str, bytes]) -> bytes:
    """A bundle from stored parts (for download)."""
    import json

    files = {"theme.json": (json.dumps(theme, indent=2) + "\n").encode()}
    files |= wallpapers
    files |= {f"icons/{n}.png": png for n, png in icons.items()}
    return _write(files)
