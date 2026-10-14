---
title: End-to-end tester
---

# End-to-end tester

`toolchain/tester/` sends real HTTP requests to a real server and checks the answers, the
same way a browser would. It complements the unit tests (`pytest`), which call the app
in-process.

```bash
crypto-helper test                 # uses toolchain/tester/config.toml
crypto-helper test --suite users   # just one suite (repeatable)
crypto-helper test --target live   # override the target
crypto-helper test --config other.toml
```
`twofa` needs `pyotp`, which the app's venv has. Everything else uses only the standard library.

Exit code: `0` all passed (or disabled), `1` a check failed, `2` bad configuration.

## Config: `toolchain/tester/config.toml`

| Key | Meaning |
|---|---|
| `[tester] enabled` | Master switch. `false` makes the tester do nothing. |
| `target` | `spawn` (default) or `live`, see below |
| `base_url`, `username` | The server and account to use in live mode |
| `password_env` | Name of the env var holding the live password. The password is never stored in the file. |
| `stop_on_fail` | Stop at the first failing check |
| `report_file` | Optional JSON report path, e.g. `toolchain/tester/reports/last.json` (gitignored) |
| `verbose` | Print every check, or only failures and suite totals |
| `[suites] <name>` | Turn each group of checks on or off |

## Targets
- **spawn**: starts a throwaway server on a free port with a temporary database, reads
  the setup token from its console, creates `super` with a random password, uses its own
  throwaway encryption key and state folder, runs the
  checks, then shuts down and deletes everything. Safe to run anytime; touches nothing real.
- **live**: tests a server that's already running, e.g. the one on port 8000:
  ```bash
  BOT_TESTER_PASSWORD='your super password' crypto-helper test --target live
  ```
  It creates throwaway users and wallets named `t_xxxxxxxx` and deletes them at the end.
  2FA is only ever turned on for those throwaway users. Its practice transfers stay in the
  transfer history (with the note `end-to-end tester`), like its entries in the audit log. It never sends
  a wrong password for your real account, so it can't lock you out. Its actions do stay in
  the audit log, which is append-only by design.

## Suites

| Suite | Checks |
|---|---|
| `health` | Server up, security headers, no-store caching, CSRF guard, no CORS, API docs hidden, setup closed |
| `auth` | Login cookie flags, no user enumeration, `/me`, forged cookie, logout, change password |
| `lockout` | 5 bad passwords lock, reset unlocks, non-consecutive failures don't lock |
| `users` | Access control, no secrets, username rules, no second root, every escalation rule, deactivate/delete revoke sessions |
| `audit` | Access control, ordering and limits, read-only, records the actor, never holds secrets |
| `twofa` | Setup, enable, login with code, replay refused, wrong codes lock, recovery codes, disable, no leaks |
| `wallets` | Access, nickname/colors/tags, seed guard, exact amounts, transfers, network refusals, delete modes, history and order |

## Adding checks
```python
# toolchain/tester/suites/wallets.py
from toolchain.tester.framework import check, expect_status


@check("wallets", "viewer can't create a wallet")
def viewer_cannot_create(ctx):
    name, _ = ctx.make_user(["wallets.view"])
    r = ctx.as_user(name).post("/api/wallets", {"name": "x", "kind": "paper"})
    expect_status(r, 403, "viewer creates wallet")
```
Then import it in `suites/__init__.py`, add it to `ALL_SUITES`, and give it a switch under
`[suites]` in `config.toml`. Useful helpers on `ctx`: `admin` (logged-in super client),
`client()` (fresh anonymous browser), `make_user(perms)` (throwaway user, cleaned up in live
mode), `as_user(name)`.
