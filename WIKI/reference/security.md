---
title: Security model
---

# Security model

## Passwords
argon2id via `argon2-cffi`, minimum 12 characters. When a username does not exist the
server still verifies against a dummy hash, so response time doesn't reveal valid names.

## Lockout
5 failed attempts in a row lock the account for 15 minutes. Wrong passwords and wrong 2FA codes
both count; a successful login resets the count. A locked, inactive, or unknown
account all return the **same** `401 Invalid username or password`, so an attacker can't
tell them apart. Failures and lockouts are written to the audit log. A wrong *current*
password on the change-password, 2FA-disable or new-recovery-codes forms also counts, so a
stolen session can't be used to guess the password.

## Two-factor login (2FA)
TOTP codes from any authenticator app (RFC 6238, via `pyotp`), plus recovery codes.
How to: [Set up 2FA]({{ site.baseurl }}/guides/set-up-2fa).

- **Enrolment is two steps.** `setup` stores a new secret but 2FA stays off until `enable`
  proves the app has it, so a typo can't lock you out.
- **Secrets are encrypted at rest** with the [secret key]({{ site.baseurl }}/reference/configuration#secret-key).
  They're only ever shown once, in the `setup` response.
- **Clock drift:** codes from the previous and next 30-second window are accepted.
- **No replays:** the time step of the last accepted code is stored, and a code from that
  step or earlier is refused, so a code seen over your shoulder can't be reused.
- **Wrong codes count toward lockout**, so 6 digits can't be brute-forced. Leaving the code
  out is the normal two-step flow and isn't counted.
- **Turning 2FA on** signs out your other sessions.
- **Recovery codes:** 10 per user, about 50 bits each, from an alphabet without look-alike
  characters. Stored only as argon2id hashes, deleted when used, replaced as a set.
  They still work if the secret key is lost.
- **Recovery without any of that:** `crypto-helper account <name> 2fa reset` on the VM.
- `super` is told `totp_setup_recommended: true` at login until 2FA is on.
- Passkeys / WebAuthn are planned for once HTTPS is set up ([Roadmap]({{ site.baseurl }}/project/roadmap)).

## Sessions
Random 256-bit token in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` when
`BOT_COOKIE_SECURE=true`). Only the SHA-256 hash is stored server-side. 12-hour expiry.
Logout deletes the session; changing a password revokes the user's *other* sessions.

## CSRF
Every non-GET request under `/api` must send `X-Requested-With: fetch`, otherwise 403.
CORS is not enabled, so other websites cannot add that header.

## Headers
Strict CSP (`default-src 'self'`, no inline script or style), `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. All `/api` responses carry
`Cache-Control: no-store`, since some contain one-time secrets. The interactive API docs
(`/docs`, `/openapi.json`) are disabled.

## Secrets at rest
| What | How it's stored |
|---|---|
| Passwords | argon2id hash |
| Session tokens | SHA-256 hash |
| 2FA secrets | Fernet-encrypted with the [secret key]({{ site.baseurl }}/reference/configuration#secret-key) |
| Recovery codes | argon2id hash |
| Setup token | In memory, plus a 0600 file in the state folder until setup is done |
| Secret key | Env var, or a 0600 file outside the repo |

## Permissions
Catalog lives in one module: `app/permissions.py`. Endpoints are protected with the
`require_permission("...")` dependency; hiding a button is never the check.
`super` always has every permission, including future ones.

| Permission | Allows |
|---|---|
| `wallets.view` | See wallets, balances, transfer history |
| `wallets.edit` | Create/edit/delete wallets, set balances |
| `prices.view` | See the currency overview |
| `transfers.create` | Create simulated transfers |
| `audit.view` | Read the audit log |
| `users.manage` | Manage users |
| `prices.manage` | Add or remove extra coins; change price history settings |

## Who can manage whom
All of these are checked on the server and covered by tests:

- `super` holds every permission, always. Nobody, including `super`, can edit, deactivate,
  reset, or delete it through the app. No second root can be created. The only way to change
  `super` is the [CLI]({{ site.baseurl }}/reference/cli) on the VM itself.
- The names `super` and `list` are reserved (`list` would clash with `crypto-helper account list`).
- You can only **grant** permissions you hold yourself.
- You can only edit or delete users whose permissions are a **subset** of yours. A manager
  with `users.manage, wallets.view` cannot even disable someone who has `audit.view`.
- Nobody edits their own account through user management. Change your own password in Settings.
- Usernames are lowercase `a-z 0-9 _ . -`, 3 to 32 characters.
- Removing a permission takes effect on the user's very next request; no re-login needed.

| Preset | Permissions |
|---|---|
| viewer | wallets.view, prices.view |
| trader | viewer + wallets.edit, transfers.create |
| admin | trader + audit.view, users.manage, prices.manage |

Presets only fill in the form. Each user stores an explicit list.

## Audit log
Append-only: time, user, action, detail, source IP. Readable with `audit.view` via `GET /api/audit`.
User events record **who did it** in `username` and the target in `detail`. Actions from the CLI
are recorded with the actor `<cli>`. Never contains passwords, tokens, 2FA secrets or recovery
codes. A username that doesn't look like a valid login name is stored as `<invalid>`,
in case someone typed a password in the wrong field.

## Seed phrase and private key guard
Every free-text field on wallets and transfers (name, nickname, provider, address, notes,
each tag, transfer note) is checked, and the request is refused if it looks like:
- 12 or more words in a row from the official BIP39 word list (SHA-256 checked when added),
- a 64-character hex private key (a transaction hash inside a `/tx/` explorer link is fine),
- a Bitcoin WIF key, an `xprv`-style extended key, or a Solana secret key / keypair file.

The answer explains the danger in plain words and never repeats the text; nothing is logged.
Validation errors in general no longer echo the input back.

## Money
Amounts are `Decimal`, stored and sent as text, never `float`; JSON numbers are refused.
Transfers take SQLite's write lock (`BEGIN IMMEDIATE`) before checking the balance, so two
transfers at once can't both spend the same coins, and each runs in one transaction, so a
crash halfway changes nothing. Both are tested (a forced crash and two racing threads).

## Web app
- Strict Content-Security-Policy: scripts, styles, fonts and images only from this server; no
  inline script or style, no `eval`. Fonts are self-hosted.
- All text reaches the page through `textContent`; the JavaScript never uses `innerHTML` or
  similar (a test fails if it does).
- Themes are data only and checked twice (server and browser): see [Themes]({{ site.baseurl }}/reference/themes).
- Only allowed client networks get any response at all (`BOT_ALLOWED_NETWORKS`), checked before
  anything else.

## Running as a service
The installed service runs as a dedicated no-login user inside a systemd sandbox (score
1.2 on systemd's 0-10 exposure scale), can read but not change its config and key, and only
listens on `127.0.0.1` unless you opt in. Details: [Service]({{ site.baseurl }}/reference/service).
Remote access options: [Remote access]({{ site.baseurl }}/guides/remote-access).

## Hard rules
No real funds before phase 4. No exchange key with withdrawal permission, ever. No seed
phrases or private keys, ever. Money is `Decimal`, never `float`.
