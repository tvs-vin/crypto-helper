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
- **Account operations** shared by the API and the CLI live in `app/accounts.py`; callers commit and audit. Wallet/holding/transfer rules live in `app/wallets.py` the same way.
- **Money:** parse with `app.money.parse_amount` (text only; JSON numbers are refused), do arithmetic with `money.add/subtract`, output with `money.format_amount`. Anything that checks a balance and then changes it calls `app.db.begin_immediate(db)` first (SQLite write lock), and runs in one transaction.
- **Free text that a user could paste a secret into** goes through `app.wallets.guard` / `app.secret_guard.find_secret` before it's stored. Never echo the rejected text; 422 handler in `app/main.py` strips `input` from validation errors.
- **Networks and coin-network table:** only in `app/networks.py` (mirrored in `WIKI/reference/networks.md`).
- **Prices:** always read through `request.app.state.prices.snapshot(db)` (one shared, cached snapshot; pass the request's session). Never call CoinGecko from a request directly. Parse provider numbers into `Decimal` (`json.loads(parse_float=Decimal)`); round fiat values with `app.prices.valuation.round_fiat`. Tests run with the mock provider and no background job (set in `tests/conftest.py`).
- **Web app** (`app/web/`, served by `app/routers/web.py`): vanilla ES modules, no build step, strict CSP. Build DOM only with `dom.js` `h()` (textContent); never `innerHTML`/`eval` (`tests/test_web.py` enforces it). Every color/size comes from a CSS variable set by a `.ctheme` (data-only, validated by `app/themes.py` and again by `js/theme.js`). Window geometry maths lives in pure `js/tiling.js` (tested by `node --test tests/js/`). Layout saves are debounced; flush them (`saveNow`) before anything ends the session. Only one sign-in box at a time (`signIn` in `main.js`).
- **Windows** live in `app/web/js/panels/`. An app may have several windows (`max` in `panels.js` = `max_windows` in `app/apps.py`; ids `overview`, `overview:2`…), so a window must never use fixed element ids or assume it's the only one; its own settings go in `ctx.windowState` / `ctx.saveWindowState(patch)` (saved with the layout). Each `render(body, ctx)` gets `ctx.signal` (aborted when the window closes): register bus listeners with `on(name, fn, ctx.signal)` (`js/bus.js`) and stop timers on it. After changing data, `emit("wallets-changed" | "transfers-changed" | "prices-changed")` so other windows refresh. Use `fill(el, ...)` (never `replaceChildren`, which prints "null"); format money with `js/format.js` (strings only, never `Number()` on amounts).
- **Writes lock first:** `get_db` starts write requests with `BEGIN IMMEDIATE`; anything else that writes (background jobs) must do the same (`IMMEDIATE` option), or parallel writes fail with "database is locked".
- **UI changes need browser proof:** run `pytest tests/ui` (real Chromium) and look at the screenshots in `tests/ui/screens/`.
- **Network access:** `BOT_HOST` may list several addresses; `BOT_ALLOWED_NETWORKS` is checked first in `app/main.py`. The main server never binds `0.0.0.0`.
- **Runtime settings that admins change** (like price history) live in the `app_settings` table as validated pydantic models, not in env vars.
- **CLI root handling:** a command that needs root re-runs itself through sudo (`app/cli/elevate.py`: `ALWAYS_ROOT`, `ROOT_WHEN_INSTALLED`, `NEVER`). Put every new command in one of those sets. `serve` must never be elevated. Tests block real `os.execv` (conftest).
- **CLI:** everything is a subcommand of `crypto-helper` (package `app/cli/`, one module per noun), noun first: `crypto-helper account <name> password`. Never accept a password or secret as a command argument (shell history, `ps`); prompt with `getpass` or read `--stdin`. CLI audit entries use the actor `<cli>`.
- **Service tooling** (`app/cli/service.py`, `update.py`, `deploy.py`, `doctor.py`): every path comes from `app/cli/layout.py`. Install code only via `deploy.install_commit` (clean `git archive`, umask 022). Any change here must pass `sudo .venv/bin/python -m toolchain.servicetest --replace-existing` on a VM without real data; it's destructive.
- **Embeds** (`app/embeds/`): the embed server is a separate app (`create_embed_app`) that may only serve embed pages, their CSS and PNGs (GET/HEAD). Anything an embed shows must have its own switch in `app/embeds/options.py` `ITEMS`; anything revealing holdings is `sensitive` and defaults off. `check_usable` re-checks the owner on every request. Where it listens: `BOT_EMBED_HOST=main` (default) follows `BOT_HOST` under the main server's bind rules; always go through `settings.embed_hosts_value`, never `embed_host` raw. Tests that need both servers: `SpawnedServer(embed=True)`.
- **Apps** (`app/apps.py`): every window is an app (or core, like settings). A new endpoint used by a window gets `dependencies=[Depends(require_app("<app>", ...))]` naming every app that calls it, next to its `require_permission`; core/account-security endpoints get none. A new window is added to `APPS` and `js/panels.js` together (`test_every_window_is_an_app_or_core`). The desktop shows what `/api/auth/me` `apps` lists.
- **Features and services** (`app/features.py`, `app/routers/services.py`): install-wide switches apply to everyone (super too); enforce with `features.require(db, key)`. Anything that needs root goes through the **agent** (`app/agent/`): add an op to `protocol.Request`, implement it in `Ops`, keep it a fixed action (never pass a command or path from the request). Endpoints that call the agent must `db.commit()` first (don't hold the write lock while it works). Throwaway servers (`SpawnedServer`) drop `BOT_*` env and get their own agent socket: keep it that way.
- **Console and Terminal** (`app/routers/shell.py`, `app/agent/console.py`, `app/agent/terminal.py`): console commands are ids mapped to fixed argv, never text. `terminal.use` is in `SUPER_GRANTS_ONLY`. The WebSocket does its own checks (HTTP middleware doesn't run for it): allowed networks, Origin, one-time ticket tied to the session, periodic re-check. xterm.js is vendored in `app/web/vendor/xterm/` (see its README); keep the canvas renderer loaded before `open()` so no `<style>` is injected under the CSP.
- **Tests run as root on this VM: never pass a real system path (`/etc/...`, `/run/crypto-helper-agent/...`, the live config) to code that writes or deletes, even as a "should be refused" example.** Use stand-ins in `tmp_path`. A mutation run that switched off a path check once deleted the VM's real `/etc/passwd` this way. Root-run code that creates files must never replace or delete anything it didn't make (link, not rename; check the inode before unlinking).
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
- Installable service like NetBird (systemd + `crypto-helper` CLI), done in 3b. Binds to 127.0.0.1; the owner uses NetBird (VM at 100.64.39.116) and SSH tunnels to reach it.
- Git: work on the `dev` branch; `main` only gets merges.

## Commands
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .   # setup
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000   # run (migrates on start)
.venv/bin/pytest                                                     # unit tests
.venv/bin/crypto-helper test                                         # end-to-end tester (toolchain/tester/config.toml)
.venv/bin/ruff check . && .venv/bin/ruff format .                    # lint / format
.venv/bin/crypto-helper --help                                       # admin CLI
node --test tests/js/                                                # window-layout maths
.venv/bin/pytest tests/ui                                            # browser tests (needs: pip install playwright && playwright install --with-deps chromium)
sudo ./install.sh                                                    # install as a systemd service
sudo crypto-helper doctor                                            # check an install
crypto-helper embed enable|disable|status                            # the embed server (asks for sudo)
sudo .venv/bin/python -m toolchain.servicetest --replace-existing    # DESTRUCTIVE full service lifecycle test
.venv/bin/alembic revision --autogenerate --rev-id 0003 -m "..."     # new migration after a model change
```
Tests use an in-memory SQLite DB via `create_app(Settings(database_url="sqlite://"))`; `tests/conftest.py` points `BOT_SECRET_KEY`, `BOT_STATE_DIR` and `CRYPTO_HELPER_ROOT` at throwaway values so tests never touch real keys or a real install (otherwise, as root on a machine with the service installed, CLI tests would switch the pytest process to the service user).
A test client must not be used as a context manager more than once per app (its exit disposes the engine).

## Status
Milestones 1-7 done (7: App manager, agent + Services window, several windows per app, Console + Terminal). Next: milestone 8 (8a scale + wallpapers, 8b theme bundles, 8c guided wallet creation), agreed scope in `WIKI/project/milestone-8.md`; read it before starting. Report after each part.
Embeds are **off** on the live install; turn them on only if the owner asks (`crypto-helper embed enable`).
The live install on this VM holds the owner's real data: deploy with `crypto-helper update`; never run `toolchain/servicetest` or seed demo data there. Screenshots for the owner go in `/root/crypto-helper-screenshots/<part>/`.
