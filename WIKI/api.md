---
title: API reference
---

# API reference

All non-GET requests need the header `X-Requested-With: fetch`.
**Built** means implemented and tested today.

| Method and path | Permission | Status |
|---|---|---|
| `GET /api/setup/status` | none | Built |
| `POST /api/setup` | setup token | Built |
| `POST /api/auth/login` | none | Built |
| `POST /api/auth/logout` | session | Built |
| `GET /api/auth/me` | session | Built |
| `POST /api/auth/password` | session | Built |
| `POST /api/auth/totp/setup`, `/enable`, `/disable` | session | Milestone 3 |
| `GET/POST /api/users`, `PATCH/DELETE /api/users/{id}` | `users.manage` | Built |
| `GET /api/meta/permissions` | `users.manage` | Built |
| `GET/POST /api/wallets`, `PATCH/DELETE /api/wallets/{id}` | `wallets.view` / `wallets.edit` | Milestone 4 |
| `PUT /api/wallets/{id}/holdings/{symbol}` | `wallets.edit` | Milestone 4 |
| `GET/POST /api/transfers` | `wallets.view` / `transfers.create` | Milestone 4 |
| `GET /api/prices`, `GET /api/prices/supported` | `prices.view` | Milestone 5 |
| `GET/PUT /api/me/preferences` | session | Milestone 5 |
| `GET /api/audit` | `audit.view` | Built |

## Users
- `GET /api/users`: list users. Never returns hashes or 2FA secrets. `locked` is true during a lockout.
- `POST /api/users`: `{"username", "password", "permissions": [...], "is_active": true}`.
- `PATCH /api/users/{id}`: any of `{"permissions": [...], "is_active": bool, "password": "..."}`.
  A password reset also clears a lockout. Deactivating or resetting a password signs the user out everywhere.
- `DELETE /api/users/{id}`: removes the user and their sessions. The username can be reused.
- `GET /api/meta/permissions`: the permission catalog and the UI presets.

Unknown fields (like `is_super`) are rejected with 422. See
[Security model]({{ site.baseurl }}/security#who-can-manage-whom) for the rules.

## Audit
`GET /api/audit?limit=100` (1 to 1000), newest first. Read-only: there is no way to edit or delete entries through the API.

## Examples
```bash
# create super (first launch only)
curl -X POST localhost:8000/api/setup -H 'X-Requested-With: fetch' \
  -H 'content-type: application/json' -d '{"token":"<from console>","password":"..."}'

# log in, keep cookie
curl -c jar -X POST localhost:8000/api/auth/login -H 'X-Requested-With: fetch' \
  -H 'content-type: application/json' -d '{"username":"super","password":"..."}'

curl -b jar localhost:8000/api/auth/me
```
