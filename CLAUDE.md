# Crypto bot: project guide for Claude Code

## What this is
A self-hosted web dashboard that will grow into a crypto trading bot. It runs on a headless VM and is used through a browser from another machine.

The owner is **new to crypto**. If something they ask for is impossible, unsafe, or unnecessary in crypto terms, say so plainly and propose the safer alternative **before** building it. Do not just comply. Explain crypto concepts in plain language when they come up (see the glossary in `docs/SPEC.md`).

All requirements, the permission model, the data model, the API and the build order are in **`docs/SPEC.md`**. Read it before starting. Work **one milestone at a time** and stop after each one to report what was built, how it was tested, and what you recommend next.

## Non-negotiable rules
1. **No real funds in phases 1 to 3.** Phase 1 uses paper balances and public price data only. No exchange credentials are stored in phase 1.
2. **Never create or accept an exchange API key with withdrawal permission.** Read-only first, trade-only later. If the owner pastes a key with withdrawal enabled, tell them to delete it and make a new one.
3. **Secrets never go in git, logs, or chat.** Passwords, API keys, session tokens, TOTP secrets and seed phrases are never logged, printed, or committed. Config comes from environment variables or a secrets file outside the repo. `.env` and `data/` are gitignored.
4. **Never ask the owner for a seed phrase or private key.** Never build a feature that stores one.
5. **Use vetted libraries for security.** argon2-cffi for password hashing, pyotp for TOTP, `secrets` for tokens, `hmac.compare_digest` for comparisons. Do not invent crypto or auth schemes.
6. **Server-side permission checks on every endpoint.** Hiding a button in the UI is not security. Every state-changing action writes an audit log entry.
7. **Money is `Decimal` (stored as string), never `float`.**
8. **Bind to `127.0.0.1` by default.** Remote access goes through an SSH tunnel, Tailscale, or Cloudflare Access, never a bare open port.
9. **Real-money transfers (phase 4):** the app never holds a key that can sign. It prepares the transaction and the owner approves it on a hardware wallet or via WalletConnect, after a small test transfer.
10. **No unattended live trading** until paper trading has run cleanly for at least 2 weeks, the kill switch has been tested, and max-loss limits are enforced in code.

## Stack (defaults, change only with the owner's OK)
- Python 3.12+, FastAPI, SQLAlchemy 2.x with SQLite, pytest
- Frontend: vanilla JavaScript ES modules, no build step, served by FastAPI from the same origin
- Strict Content-Security-Policy (no inline scripts); build DOM with `textContent` / element APIs, never `innerHTML` with data
- Ask before adding dependencies that touch money or networks (exchange SDKs, web3 libraries)

## Conventions
- Every endpoint gets tests, **including the permission-denied cases**.
- One commit per milestone minimum, with a clear message.
- Keep the permission catalog in one module so new features can add permissions in one place.
- When commands exist (run, test, lint), add them to the section below.
- **Schema changes ship as an Alembic migration** in `app/migrations/versions/` (numbered `0003`, `0004`, ...; see `WIKI/reference/database-migrations.md`). `test_migrations_build_exactly_the_models` fails if models and migrations disagree.
- **Secrets at rest are encrypted** with `app.crypto` (`request.app.state.secret_box`). Never store a credential in plain text.
- **Account operations** shared by the API and the CLI live in `app/accounts.py`; callers commit and audit.
- **CLI:** everything is a subcommand of `crypto-helper` (`app/cli.py`), noun first: `crypto-helper account <name> password`. Never accept a password or secret as a command argument (shell history, `ps`); prompt with `getpass` or read `--stdin`. CLI audit entries use the actor `<cli>`.
- **End-to-end checks:** when you add an endpoint, add checks in `toolchain/tester/suites/` too (new suite: register it in `suites/__init__.py` and give it a switch in `config.toml`). In live mode the tester may only change throwaway `t_*` users.

## Wiki (`WIKI/`, Jekyll, published to GitHub Pages by `.github/workflows/wiki.yml`)
The owner wants it hyper organized. Update it in the same commit as the behaviour it describes.
- `guides/`: numbered how-to steps. `reference/`: exact, complete facts, one area per page. `project/`: roadmap and decisions. `tools/`: **only** docs for testing tools we build (not the app's CLI, which is `reference/cli.md`). `glossary.md`: terms.
- Every section has an `index.md` listing its pages; new pages go in it and in the table on `WIKI/index.md`.
- Link with `{{ site.baseurl }}/section/page`. Check links resolve before committing.

## Decisions
Owner's answers (details in `WIKI/project/decisions.md`):
- Support both exchange accounts and self-custody wallets; everything customizable.
- Comfortable with Python. Wants thorough docs in `WIKI/`.
- First bot job: track and alert.
- US-based: keep a tax-friendly trade log; prefer US-available exchanges.
- 2FA: TOTP + recovery codes only (free, offline, self-hosted). Passkeys parked until HTTPS.
- Should become an installable service like NetBird (systemd + `crypto-helper` CLI): milestone 3b.
- Git: work on the `dev` branch; `main` only gets merges.

## Commands
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .   # setup
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000   # run (migrates on start)
.venv/bin/pytest                                                     # unit tests
.venv/bin/crypto-helper test                                         # end-to-end tester (toolchain/tester/config.toml)
.venv/bin/ruff check . && .venv/bin/ruff format .                    # lint / format
.venv/bin/crypto-helper --help                                       # admin CLI
.venv/bin/alembic revision --autogenerate --rev-id 0003 -m "..."     # new migration after a model change
```
Tests use an in-memory SQLite DB via `create_app(Settings(database_url="sqlite://"))`; `tests/conftest.py` points `BOT_SECRET_KEY` and `BOT_STATE_DIR` at throwaway values so tests never touch real keys.
A test client must not be used as a context manager more than once per app (its exit disposes the engine).

## Status
Milestones 1 (auth), 2 (users, permissions, audit) and 3 (2FA, recovery codes, migrations, encryption at rest, CLI) done. Next: milestone 3b (installable service).
