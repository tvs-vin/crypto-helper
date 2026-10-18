---
title: Phase 1 review
---

# Phase 1 review (milestone 10b, 2026-10-17)

A full review of the app before the v1.0.0 release: automated checks that now run with the
tests, and a read-through of every endpoint. This page lists what was checked, what was found,
and what changed.

## Checks that now run with every test run
| Check | Test |
|---|---|
| Every API route (95, read from the app's own route table) refuses a caller without a session, except 5 public ones (setup status, setup, login, logout, the page). It's asked of every route for real, so routes that check the session themselves are covered too. | `tests/test_route_audit.py` |
| Every route that changes something writes an audit entry, or is on a short list that says why not (your own display settings, your own notifications, a test message to your own webhook). | `tests/test_route_audit.py` |
| API request bodies over 2 MB are refused before they're read (the two uploads stream and have their own limits). | `tests/test_route_audit.py` |
| No secret reaches the servers' output: both servers are started as the service starts them, taken through setup, sign-in, wrong passwords, 2FA, a recovery code, a webhook, an embed link, a ticket in a URL and a password change, and then their output is searched for each secret. | `tests/test_log_secrets.py` |
| Reading prices or adding a coin never holds a database lock while the price source answers. | `tests/test_prices_api.py`, `tests/test_price_engine.py` |
| Settings, `.env.example` and the configuration reference agree; wiki links resolve. | `tests/test_docs.py`, `tests/test_help.py` |

**Dependencies:** `pip-audit` on the exact versions installed (the live install and the
development environment, 33 packages): no known vulnerabilities.

## Found and fixed
| # | What | Risk | Fix |
|---|---|---|---|
| 1 | **Embed links and the Terminal's one-time ticket were written to the system journal** (the web server's access log shows each address). On the live install the journal held one embed link (from 2026-10-16). | Anyone who can read the journal (root, the `adm` group) could open that embed. | The access log now hides embed tokens and drops query strings (`app/logredact.py`). **To do on the live install:** press **New link** on your embed so the logged one stops working. |
| 2 | **Turning on 2FA didn't ask for the password.** Turning it off did. | Someone with a stolen session (but not the password) could put their own authenticator on the account, which signs out and locks out its owner. | `/api/auth/totp/enable` now needs the password; a wrong one counts toward lockout. |
| 3 | **Database locks held during price fetches.** Adding a coin held the write lock while asking CoinGecko; reading prices held a read lock while fetching; adding a price alert could fetch while holding the write lock. | CoinGecko can take up to 10 s; other writes give up after 5 s with "database is locked". | Fetches happen with no lock held; requests that write use the last prices fetched. |
| 4 | **A cached embed picture outlived its link** for up to 2 minutes after the embed was switched off, expired or given a new link. | A link that should have stopped still showed its picture briefly. | The link is checked on every request; only the drawing is cached. |
| 5 | **No recovery-phrase guard on embed names and headings, or on theme text.** | Both can be seen by others (a public embed, a published theme). | Guarded like other free text. |
| 6 | **The two upload routes answered "invalid request" before checking the session.** | Harmless, but the rule is that nothing answers without a session. | The session is checked first. |
| 7 | **Saving your wallet order** needed only a session, and its error named which wallet ids exist. | Wallet ids only. | Needs `wallets.view`, like the wallet list. |
| 8 | **No limit on API request size.** | A signed-in client could make the server read a huge body. | 2 MB, uploads excepted. |

Found while building 10a (same release): the price alerts list didn't refresh when an alert
fired; a broken link in the install guide.

## Looked at and fine
- Sign-in, sessions, lockout, setup token, 2FA codes and recovery codes; every permission and
  ownership check in users, wallets, transfers, prices, embeds, themes, wallpapers,
  notifications, price alerts, apps and services; what each endpoint returns.
- The embed server (separate app, GET only, every value escaped, its own CSP), the Console
  and Terminal path (fixed commands; 2FA; password and code to open; one-time ticket tied to
  the session; Origin check; periodic re-check), the agent's fixed operations.
- Uploads (re-encoded, never stored as sent), the notification stream, background jobs.

## Not changed, for the owner to decide
- **Pinned dependencies.** `requirements.txt` and `pyproject.toml` name packages without
  versions, so an update installs whatever is newest that day (FastAPI changed how it lists
  routes during this milestone). Recommended for 10c: pin exact versions, tested, and bump them
  on purpose.
- **Wallets are shared** by everyone with `wallets.view` (the household model from milestone 4).
  If accounts should ever have private wallets, that's a design change for phase 2.
