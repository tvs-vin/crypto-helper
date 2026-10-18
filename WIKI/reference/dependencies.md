---
title: Dependencies
---

# Dependencies

Crypto Helper runs on **exact, tested versions** of every Python package, so an update never
picks up a new release by surprise.

| File | Holds | Used by |
|---|---|---|
| `requirements.txt` | Every package the app runs on, its dependencies included, as `name==version` | `install.sh` and `crypto-helper update` (as pip *constraints*), CI |
| `requirements-dev.txt` | `requirements.txt` plus the test tools (pytest, ruff, Playwright…), also pinned | development, CI |
| `pyproject.toml` | The packages the app needs, by name | building the package |

Tests check that every package `pyproject.toml` names is pinned, and that the tests themselves
run on exactly the pinned versions (`tests/test_packaging.py`), so the pins never describe
something that wasn't tested.

## Upgrading a package
1. Change its version (and any dependency that has to move with it) in `requirements.txt`.
2. In a development checkout: `.venv/bin/pip install -r requirements-dev.txt`.
3. Run everything: `.venv/bin/pytest`, `.venv/bin/pytest tests/ui`, `node --test tests/js/*.test.mjs`,
   `.venv/bin/crypto-helper test`.
4. Check for known vulnerabilities:
   `pip-audit --no-deps --disable-pip -r requirements.txt` (pip-audit in a separate venv).
5. Commit, and note it in `CHANGELOG.md`. Installs get it with the next `crypto-helper update`.

## Python
Tested on Python 3.13 (CI and the reference install). `pyproject.toml` asks for 3.12 or newer.

## Outside Python
- **systemd** and **git**, to install and update.
- **ffmpeg** (optional), for video wallpapers.
- Vendored in the repository, no CDN: fonts (Inter, Mona Sans, JetBrains Mono) and xterm.js
  (`app/web/vendor/xterm/`, see its README for the version).
