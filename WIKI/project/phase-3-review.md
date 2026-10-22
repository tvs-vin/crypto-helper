---
title: Phase 3 review
---

# Phase 3 review (milestone 12e, 2026-10-22)

A review of everything phase 3 added (milestone 12: onboarding, smarter alerts, daily and past
prices, live windows, the backtester, paper trading, readiness) before the v1.2.0 release:
the automated checks that now run with the tests, a read-through of every new endpoint and job,
and a dependency audit. This page lists what was checked, what was found, and what changed.

## Checks that now run with every test run
| Check | Test |
|---|---|
| Every route (now 150) still refuses a caller without a session (except the public list), every change is audited or says why not, and bodies are capped at 2 MB. Phase 3 added 3 routes whose audit entry is written by shared code (the kill switch, re-arm and drill go through `app.bots.trip` / `rearm`, which the CLI uses too); the test follows them there. | `tests/test_route_audit.py` |
| Every route refuses an account with a pending rule (a new password or 2FA required), except the few it needs to fix that. | `tests/test_account_rules.py` |
| Every API write route is mapped to the live-update topics it changes, and each topic only reaches accounts allowed to see it. | `tests/test_live.py` |
| Paper trading's safety: limits cut orders, a coin's loss pauses, a day's loss and stale prices trip the kill switch, practice prices never fill, the kill switch stops everything until re-armed (API and CLI), who may do what. | `tests/test_bots.py` |
| Readiness: what counts as a clean day and what starts it again, drills (including one that didn't stop the bot check), the self-check catching a broken engine, a changed engine needing a new self-check. | `tests/test_readiness.py` |
| Uninstalling: a full install into a throwaway folder, purged, leaves nothing but the final copy; the dry run lists exactly what the real run removes and changes nothing. | `tests/test_uninstall.py` |
| Phase 3's guards are **mutation-checked**: 64 of them (backtester, paper trading, readiness, uninstall and this review's fixes) are switched off one at a time to prove a test notices. 63 are caught; the last can't change behaviour (drills are only recorded once re-armed, so a second "re-armed" condition is a second lock on the same door). | `python -m toolchain.checks --mutations` |

The checks now run on every core (`toolchain/checks.py`): a full run takes about 7 minutes
instead of 19. Running in parallel found a real race in the app (below, #8) and four tests
that depended on timing, all fixed.

**Dependencies:** `pip-audit` on the exact pinned versions and on the live install's. Before:
Pillow 12.3.0 with 31 known vulnerabilities (#2), and certifi in the test tools (#3). After:
no known vulnerabilities in either.

## Found and fixed
| # | What | Risk | Fix |
|---|---|---|---|
| 1 | **The kill switch's "why" wasn't checked for a pasted secret.** Bot names were, but the reason typed when stopping all bots (or running a drill, or on the command line) wasn't. | It goes to the audit log, everyone's notifications and Discord. A seed phrase pasted there by mistake would have been spread around. | Guarded like all other free text (API and CLI); never echoed back. |
| 2 | **Pillow 12.3.0** had 31 published vulnerabilities (memory errors and denial of service in its TIFF, GIF, PNG, EPS, PDF and other decoders). | Pillow opens pictures people upload (wallpapers, theme icons). A crafted file could crash or hang the server, or worse. | Upgraded to **13.0.0**. And as a second layer: an upload is now opened only by the decoder for the type it says it is (PNG, JPEG, GIF or WebP), so Pillow's other decoders never see one, whatever bugs they have in future. |
| 3 | **certifi** (test tools only) trusted a certificate authority whose keys leaked. | Only the development machine's HTTPS checks; the server doesn't use it. | Updated. |
| 4 | **Removing an extra coin that a paper bot trades** was allowed. | The bot could never get a price again: "running", with orders waiting forever. | Refused while a bot uses the coin. |
| 5 | **Readiness counted days for a bot that wasn't really being checked** (the service stopped, or no price for its coin). | Two clean weeks could be claimed for a bot nobody was watching. | A check only counts when it had prices to trade on; with none for 6 hours, the bot has 0 clean days until it runs again. |
| 6 | **The command-line kill switch could fail with "database is locked"** while the server was writing. | The kill switch has to work when other things are busy. | It takes the write lock first and tries again for about 30 seconds. |
| 7 | **Uninstall from a test folder would still have touched the real system** (stopped the real services, deleted an account by name), deleted `/usr/local/bin/crypto-helper` whatever it was, and left `systemctl edit` overrides and the backup timer's stamp behind. | Only reachable with `CRYPTO_HELPER_ROOT` set, but the tests run as root on the live VM. | One plan for the real run and `--dry-run`; systemd and accounts only on the real root; the link only if it points into the install; the account only if the installer made it (never root); overrides and the stamp removed. |
| 8 | **The agent's client reported "Broken pipe" instead of the agent's answer** when the agent refused a request and hung up quickly (a busy machine made this happen). | A confusing error instead of "not allowed". | It reads the answer even when its own send was cut short. |
| 9 | **The mutation runner counted a broken run as "caught"**: a mutation whose test file didn't exist (or whose change didn't even parse) made pytest fail to start, and that looked like the tests noticing. Re-running every phase 3 mutation with the fix found 3 backtester checks no test covered (a sale's price at the next open less slippage, and the history needed before the start date). | Missing tests could hide behind a green mutation run. | Only failing tests count; anything else is reported as "bad tests". The 3 tests were added. |

Found while building phase 3 and fixed in its parts (same release): in-place changes to saved
JSON being lost (alerts, bots); a background job skipping its first run after a reboot; an
HTTP middleware that ran before the database session closed (live windows); the Backtester's
window state being refused; order values shown to 7 decimals; fixed sleeps in browser tests.

## Looked at and fine
- Onboarding: server steps are super's only; network changes are checked twice (web app and
  agent), never `0.0.0.0`, and undone unless the restarted server confirms.
- Alerts: each person's own; parameters are validated numbers and symbols (no free text);
  holdings reach Discord only through the detail switches.
- Daily and past prices: imports need `prices.manage`, run without holding the database lock,
  one at a time; imported prices never replace recorded ones.
- Live windows: only topic names travel; each topic goes only to accounts allowed to see it;
  the admin remote open needs `users.manage`, follows the usual rules for managing that
  account, is audited and rate-limited.
- Backtester: at most 10 coins and 30 years per run; saved runs are each person's own; trades
  CSV can't carry spreadsheet formulas.
- Paper trading: no code path to an exchange (the exchange clients still contain only reading
  calls, enforced by a test); money stays Decimal; the bot check holds the database lock only
  while it writes (prices are fetched before); every change is audited.

## Not changed, for the owner to decide
- **Bots are shared**, like wallets: anyone with `bots.run` can pause, start or delete any bot,
  not just their own (and `bots.view` sees them all). That suits one household. If accounts
  should have private bots, it's a small change.
- **The 14 days and the 90-day drill** are the rule as written (project rule 10); stricter
  values (say 30 days) are a one-line change.
- A development key in `/root/.config/crypto-helper/` (from running the app from a checkout as
  root on 2026-10-16) isn't part of the install and isn't used by it; delete it if you like.
