---
title: Browser tests
---

# Browser tests

`tests/ui/` drives the real web app in headless Chromium (Playwright) against a real
server process, the way you'd use it.

```bash
.venv/bin/pip install playwright && .venv/bin/playwright install --with-deps chromium   # once
.venv/bin/pytest tests/ui            # just the browser tests (~40 s)
.venv/bin/pytest                     # everything; browser tests skip if Chromium is missing
node --test tests/js/                # the window-layout maths, without a browser
```

Each test saves a screenshot of how it ended in `tests/ui/screens/` (gitignored) for a human
to look at. Any JavaScript error or Content-Security-Policy violation fails the test.

## What's covered
| Test | Proves |
|---|---|
| First launch | Setup box → create super → sign in → box closes on the same page; 2FA nudge |
| Mismatched / wrong password | Clear errors, the box stays, the password field clears |
| Two-factor | Code step appears; recovery code works |
| Permissions | The launcher only lists windows you're allowed |
| Drag and snap | Dragging to the edge shows the outline and snaps to half; the layout comes back in a new browser |
| Tiled mode | No overlaps; the mode is remembered |
| Keyboard, minimize, taskbar, maximize, close | The shortcuts and buttons |
| Themes | Apply at once; follow the user to another browser |
| Malicious theme | The browser refuses URLs, CSS and fonts outside the list |
| Session expiry | The box returns over the same windows; the action that hit the expiry still happens |
| Sign out and in | No second box; the last layout change is kept |
| Phone width | Windows stack, no sideways scrolling |
| Reload right after a change | The last layout change survives (sent as the page closes) |
| Wallet cards | Nickname, name, user and built-in tags, two-color band, values; no stray "null" |
| Create / edit wallet | Every field, network, tags, custom second color |
| Seed phrase in a form | Refused with an explanation, not echoed, nothing saved |
| Set a balance | Exact amounts; BTC on an Ethereum wallet refused |
| Group by coin, archive, drag to reorder | Totals and holders; archived hidden/shown; your order survives a reload |
| Delete flows | Empty wallet still asks; force needs the exact name; move-everything-then-delete |
| Transfers | Sent from the form; the Wallets window updates itself; cross-network refused with the reason; Max |
| Overview | Watchlist star survives reload; yen has no decimals; hide a column; chart draws, scrolls into view, hover shows an exact price |
| Audit | Search filters the rows |
| Read-only user | No create/edit/send controls, no values |
| 2FA from Settings | QR image loads, code confirms, 10 recovery codes, taskbar marker clears, the next sign-in asks for a code |
| Password and sessions | Change password then sign in with it; see two sessions and sign the other out |
| Themes | Upload → preview → discard/save → still in use after reload; bad files refused before anything changes; template download; admin publishes and another user applies it |
| Display, prices, system | Watchlist chips, reset layout; history settings persist; extra coin with look-alike confirmation; System only for super |
| Users window | Create from a preset, edit, deactivate, delete; a manager can't grant what they lack or touch super/themselves |
| Several windows | Two Overviews keep their own currency and chart through a reload; the limit of 4 (no **+**, Ctrl+Alt+N says so), closing one frees its number, Settings opens once; Ctrl+click opens another; tiled windows don't overlap; the taskbar brings back the right one. Any failed layout save fails every browser test. |
| App manager | Untick Wallets for an account: it's gone from their menu and their saved layout; off for everyone spares super; a manager can't switch apps they can't use, super, or themselves; the shield explains a missing permission; no App manager without the permission |
| Services | With a test agent (systemctl recorded): embed switch, back up now, restart web; paper wallets off really refuses a paper wallet; practice prices warning; without an agent: the notice and command, system switches greyed, features still work; hidden without the permission |
| Embeds | Make one in Settings, the preview picture loads, open its link on the real embed server (no amounts or values, no script, OpenGraph picture); switch on amounts/values with the warning; a listed local website can frame it and another can't; turn off, new link, delete (old links 404); hidden without the permission; the "server is off" notice |

`SpawnedServer(embed=True)` (in `toolchain/tester/server.py`) also starts the embed server on
its own port; the embed tests and the end-to-end tester use it. The framing test hosts its two
"websites" on local ports, because Chromium never lets a public site frame a `127.0.0.1`
address.

The tests use seeded data (`tests/ui/seed.py`: five wallets across networks, a transfer and a
day of BTC history). If a test fails, the server's log is printed with it.
