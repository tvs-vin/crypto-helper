---
title: API reference
---

# API reference

All non-GET requests need the header `X-Requested-With: fetch`. Every `/api` response is
sent with `Cache-Control: no-store`.
**Built** means implemented and tested today.

| Method and path | Permission | Status |
|---|---|---|
| `GET /api/setup/status` | none | Built |
| `POST /api/setup` | setup token | Built |
| `POST /api/auth/login` | none | Built |
| `POST /api/auth/logout` | session | Built |
| `GET /api/auth/me` | session | Built |
| `POST /api/auth/password` | session | Built |
| `POST /api/auth/totp/setup`, `/enable`, `/disable` | session | Built |
| `POST /api/auth/totp/recovery-codes` | session | Built |
| `GET/POST /api/users`, `PATCH/DELETE /api/users/{id}` | `users.manage` | Built |
| `GET /api/meta/permissions` | `users.manage` | Built |
| `GET/POST /api/wallets`, `PATCH/DELETE /api/wallets/{id}` | `wallets.view` / `wallets.edit` | Milestone 4 |
| `PUT /api/wallets/{id}/holdings/{symbol}` | `wallets.edit` | Milestone 4 |
| `GET/POST /api/transfers` | `wallets.view` / `transfers.create` | Milestone 4 |
| `GET /api/prices`, `GET /api/prices/supported` | `prices.view` | Milestone 5 |
| `GET/PUT /api/me/preferences` | session | Milestone 5 |
| `GET /api/audit` | `audit.view` | Built |

## Login
`POST /api/auth/login` with `{"username", "password", "totp"?}`.

| Situation | Answer |
|---|---|
| Wrong password, unknown, locked or inactive account | `401 {"detail": "Invalid username or password"}` |
| Right password, 2FA on, no `totp` | `401 {"detail": "2FA code required", "totp_required": true}` (not counted as a failure) |
| Right password, wrong code | `401 {"detail": "Invalid 2FA code", "totp_required": true}` (counts toward lockout) |
| Success | `200 {"username", "totp_setup_recommended"}` and the session cookie |

`totp` is a 6-digit authenticator code or a [recovery code]({{ site.baseurl }}/guides/recovery-codes).
`totp_setup_recommended` is true for `super` until 2FA is on.

`GET /api/auth/me` returns `id, username, is_super, permissions, totp_enabled, recovery_codes_left, preferences`.

## 2FA
| Endpoint | Body | Answer |
|---|---|---|
| `POST /api/auth/totp/setup` | none | `{"secret", "otpauth_uri"}`. 409 if 2FA is already on. Calling again replaces the pending secret. |
| `POST /api/auth/totp/enable` | `{"code"}` | `{"recovery_codes": [10 codes]}`, shown once. 400 if wrong code or no setup; 409 if already on. Signs out your other sessions. |
| `POST /api/auth/totp/disable` | `{"password"}` | `{"ok": true}`. 403 wrong password (counts toward lockout); 400 if 2FA is off. |
| `POST /api/auth/totp/recovery-codes` | `{"password"}` | A fresh set of 10; the old ones stop working. 403 / 400 as above. |

Walkthrough: [Set up 2FA]({{ site.baseurl }}/guides/set-up-2fa).

## Users
- `GET /api/users`: list users. Never returns hashes or 2FA secrets. `locked` is true during a lockout.
- `POST /api/users`: `{"username", "password", "permissions": [...], "is_active": true}`.
- `PATCH /api/users/{id}`: any of `{"permissions": [...], "is_active": bool, "password": "..."}`.
  A password reset also clears a lockout. Deactivating or resetting a password signs the user out everywhere.
- `DELETE /api/users/{id}`: removes the user and their sessions. The username can be reused.
- `GET /api/meta/permissions`: the permission catalog and the UI presets.

Unknown fields (like `is_super`) are rejected with 422. See
[Security model]({{ site.baseurl }}/reference/security#who-can-manage-whom) for the rules.

## Audit
`GET /api/audit?limit=100` (1 to 1000), newest first. Read-only: there is no way to edit or delete entries through the API.

## Examples
```bash
# create super (first launch only; token from `crypto-helper setup token`)
curl -X POST localhost:8000/api/setup -H 'X-Requested-With: fetch' \
  -H 'content-type: application/json' -d '{"token":"<token>","password":"..."}'

# log in, keep cookie
curl -c jar -X POST localhost:8000/api/auth/login -H 'X-Requested-With: fetch' \
  -H 'content-type: application/json' -d '{"username":"super","password":"..."}'

curl -b jar localhost:8000/api/auth/me
```
