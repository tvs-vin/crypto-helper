"""Every non-Python file the app uses must be in the installed package. Tests run from the
checkout, so a file missing from package-data only breaks the real install (6d shipped
without embeds/static/embed.css that way)."""

import fnmatch
import re
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


def test_every_wiki_page_is_installed():
    """The Help window reads the wiki from the install (pyproject data-files)."""
    files = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["data-files"]
    globs = [g for patterns in files.values() for g in patterns]
    missing = [
        rel
        for f in (ROOT / "WIKI").rglob("*.md")
        if not any(
            fnmatch.fnmatch(rel := f.relative_to(ROOT).as_posix(), g)
            and rel.count("/") == g.count("/")
            for g in globs
        )
    ]
    assert not missing, f"add to [tool.setuptools.data-files] in pyproject.toml: {missing}"
    for dest, patterns in files.items():  # each folder lands where app/help.py looks
        for g in patterns:
            sub = g.removeprefix("WIKI/").rpartition("/")[0]
            assert dest == "share/crypto-helper/wiki" + (f"/{sub}" if sub else ""), (dest, g)


def _pins(name: str) -> dict[str, str]:
    pins = {}
    for line in (ROOT / name).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-r ")):
            continue
        assert re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9A-Za-z.+-]+", line), f"{name}: {line!r}"
        pkg, version = line.split("==")
        pins[_norm(pkg)] = version
    return pins


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_every_dependency_is_pinned():
    """Installs use requirements.txt as constraints: every dependency needs an exact version."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    runtime = _pins("requirements.txt")
    for dep in project["dependencies"]:
        name = _norm(re.split(r"[\[<>=!~ ]", dep, maxsplit=1)[0])
        assert name in runtime, f"pin {name} in requirements.txt"
    dev = _pins("requirements-dev.txt")
    assert "-r requirements.txt" in (ROOT / "requirements-dev.txt").read_text()
    for dep in project["optional-dependencies"]["dev"]:
        assert _norm(dep) in dev, f"pin {dep} in requirements-dev.txt"


def test_tests_run_on_the_pinned_versions():
    """Otherwise the pins would describe something that was never tested."""
    from importlib.metadata import PackageNotFoundError, version

    wrong = []
    for name, pinned in {**_pins("requirements.txt"), **_pins("requirements-dev.txt")}.items():
        try:
            have = version(name)
        except PackageNotFoundError:
            have = None
        if have != pinned:
            wrong.append(f"{name}: pinned {pinned}, installed {have}")
    assert not wrong, "\n".join(wrong)
