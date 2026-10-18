"""The documentation that describes settings can't drift from the code."""

import re
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent


def _fields() -> dict[str, object]:
    return {f"BOT_{k.upper()}": v.default for k, v in Settings.model_fields.items()}


def _shown(default) -> str:
    if default is None:
        return ""
    if isinstance(default, bool):
        return "true" if default else "false"
    if isinstance(default, float) and default.is_integer():
        return str(int(default))
    return str(default)


def test_env_example_lists_every_setting_with_its_default():
    text = (ROOT / ".env.example").read_text()
    listed = dict(re.findall(r"^# (BOT_[A-Z_]+)=(.*)$", text, re.M))
    assert set(listed) == set(_fields()), "add or remove settings in .env.example"
    for name, default in _fields().items():
        assert listed[name] == _shown(default), f"{name}: .env.example says {listed[name]!r}"
    # Nothing is switched on by the example itself: every setting line is a comment.
    assert not re.search(r"^BOT_", text, re.M)


def test_configuration_reference_lists_every_setting():
    text = (ROOT / "WIKI/reference/configuration.md").read_text()
    documented = set(re.findall(r"`(BOT_[A-Z_]+)`", text))
    assert set(_fields()) <= documented, sorted(set(_fields()) - documented)


def test_readme_and_changelog_links_exist():
    for name in ("README.md", "CHANGELOG.md"):
        text = (ROOT / name).read_text()
        local = [t for t in re.findall(r"\]\(([^)]+)\)", text) if not t.startswith("http")]
        assert local and all((ROOT / t).exists() for t in local), (name, local)


def test_changelog_has_this_version():
    import tomllib

    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert f"## {version} " in (ROOT / "CHANGELOG.md").read_text()
