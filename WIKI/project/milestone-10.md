---
title: Milestone 10 plan
---

# Milestone 10: wrap-up and release (end of phase 1)

Agreed with the owner on 2026-10-17. Three parts, reported one by one.

| Part | Status |
|---|---|
| 10a. README, `.env.example`, the Help window | Done |
| 10b. Phase 1 review (security and quality) | Planned |
| 10c. CI, changelog, merge to `main`, tag v1.0.0 | Planned |

Owner's answers: the wiki readable **both** in the app and on GitHub Pages; **merge `dev` into
`main` and tag v1.0.0** after the review (work carries on on `dev`; the live install keeps
following `dev`); CI runs **lint and unit tests** on every push; a **full** review.

## 10a: getting started, and Help in the app
- `README.md`: what it is (and isn't: no real funds yet), install as a service, first launch
  (setup token, `super`, 2FA), reaching it remotely, updating, backups, where the docs are.
  Short: it points into the wiki rather than repeating it.
- `.env.example`: every `BOT_*` setting with its default and a one-line comment, in the order of
  `WIKI/reference/configuration.md`. A test fails if `app/config.py` gains a setting that isn't
  in it (or it lists one that doesn't exist).
- **Help window**, open to everyone signed in (a core app, like Settings): the wiki's pages,
  from the installed copy, so they always match the version you run, offline.
  - The server reads `WIKI/` (a fixed folder; page names checked against a list built at
    start-up, never a path from the request) and turns the Markdown into a small, safe
    structure (headings, paragraphs, lists, tables, code, links, bold/code inline).
  - The browser builds it with `h()` like everything else: no HTML from the pages is ever
    inserted (the CSP and `test_web.py` rules stay as they are).
  - Wiki links (`{{ site.baseurl }}/guides/…`) open the page inside Help; outside links show
    their address and open in a new tab. Navigation by section, and a search box over titles
    and headings.
  - A "?" in other windows' title bars could open the matching guide (if it stays simple).
- Built: the "?" is in every window's title bar. The wiki ships with the install
  (`pyproject` data-files, checked by a test), and a test checks every link between wiki pages
  and every `#anchor` (one broken anchor was found and fixed).
- GitHub Pages stays set up (publishing from `main`). It starts working once the repo is public
  or on a plan that allows Pages for private repos; nothing else to change then.

## 10b: phase 1 review
Automated, kept as tests so they keep holding:
- **Every API route** checks a permission or a signed-in session, or is on a short, explicit
  list of public ones (login, setup, health, static files) with the reason.
- **Every state-changing route** writes an audit entry (checked against the list of routes).
- **No secrets in logs:** run the end-to-end tester with logging at DEBUG and search the log for
  every password, token, TOTP secret, webhook address and recovery code it used.
- **Dependencies:** `pip-audit` against `requirements.txt`; anything found is upgraded or
  explained.

Read-through, with findings written up and fixed:
- Each router: permission and app checks, ownership checks (only your own), input limits,
  what's returned (no hashes, secrets or other people's data).
- The agent and the Console/Terminal path again, the embed server, uploads, the notification
  stream, background jobs (locks, errors).
- Report: what was checked, what was found, what changed. Anything too big becomes a decision
  for the owner rather than a silent change.

## 10c: release
- **CI** (`.github/workflows/tests.yml`): on every push and pull request, ruff and the unit
  tests (not the browser tests, to keep within the free minutes).
- `CHANGELOG.md`: v1.0.0 summarising milestones 1-10, then a section per release from here on.
  Version 1.0.0 in `pyproject.toml` (shown by `crypto-helper version` and in Settings → System).
- Merge `dev` into `main` (a pull request, so CI runs on it), tag `v1.0.0`.
- Roadmap: phase 1 done; the next step is planning phase 2 (read-only exchange keys and
  on-chain balances by public address) with the owner.
