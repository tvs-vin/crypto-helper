---
title: Security model
---

# Security model

## Passwords
argon2id via `argon2-cffi`, minimum 12 characters. When a username does not exist the
server still verifies against a dummy hash, so response time doesn't reveal valid names.

## Lockout
5 failed attempts lock the account for 15 minutes. A locked, inactive, or unknown
account all return the **same** `401 Invalid username or password`, so an attacker can't
tell them apart. Failures and lockouts are written to the audit log. A wrong *current*
password on the change-password form also counts, so a stolen session can't be used to
guess the password.

## Sessions
Random 256-bit token in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` when
`BOT_COOKIE_SECURE=true`). Only the SHA-256 hash is stored server-side. 12-hour expiry.
Logout deletes the session; changing a password revokes the user's *other* sessions.

## CSRF
Every non-GET request under `/api` must send `X-Requested-With: fetch`, otherwise 403.
CORS is not enabled, so other websites cannot add that header.

## Headers
Strict CSP (`default-src 'self'`, no inline script or style), `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. The interactive API docs
(`/docs`, `/openapi.json`) are disabled.

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

## Who can manage whom
All of these are checked on the server and covered by tests:

- `super` holds every permission, always. Nobody, including `super`, can edit, deactivate,
  reset, or delete it. The name `super` is reserved, and no second root can be created.
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
| admin | trader + audit.view, users.manage |

Presets only fill in the form. Each user stores an explicit list.

## Audit log
Append-only: time, user, action, detail, source IP. Readable with `audit.view` via `GET /api/audit`.
User events record **who did it** in `username` and the target in `detail`. Never contains passwords, tokens or
secrets. A username that doesn't look like a valid login name is stored as `<invalid>`,
in case someone typed a password in the wrong field.

## Hard rules
No real funds before phase 4. No exchange key with withdrawal permission, ever. No seed
phrases or private keys, ever. Money is `Decimal`, never `float`.
