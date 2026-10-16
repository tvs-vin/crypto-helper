"""Every non-Python file the app uses must be in the installed package. Tests run from the
checkout, so a file missing from package-data only breaks the real install (6d shipped
without embeds/static/embed.css that way)."""

import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_app_data_file_is_packaged():
    globs = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"][
        "package-data"
    ]["app"]
    missing = []
    for f in (ROOT / "app").rglob("*"):
        if not f.is_file() or f.suffix in (".py", ".pyc") or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(ROOT / "app").as_posix()
        # setuptools globs don't cross folders: "web/js/*.js" doesn't match web/js/panels/x.js.
        if not any(fnmatch.fnmatch(rel, g) and rel.count("/") == g.count("/") for g in globs):
            missing.append(rel)
    assert not missing, f"add to [tool.setuptools.package-data] in pyproject.toml: {missing}"
