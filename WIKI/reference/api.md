---
title: API reference
---

# API reference

All non-GET requests need the header `X-Requested-With: fetch`. Every `/api` response is
sent with `Cache-Control: no-store`. Validation errors (`422`) say where and why, but never
repeat the input back (it could be a password or a pasted seed phrase).
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
| `GET/POST /api/wallets`, `PATCH/DELETE /api/wallets/{id}` | `wallets.view` / `wallets.edit` | Built |
| `PUT /api/wallets/{id}/holdings/{symbol}` | `wallets.edit` | Built |
| `GET /api/wallets/{id}`, `GET /api/holdings/summary`, `GET /api/meta/networks` | `wallets.view` | Built |
| `PUT /api/me/wallet-order` | session | Built |
| `GET/POST /api/transfers` | `wallets.view` / `transfers.create` | Built |
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

## Wallets
Walkthrough: [Wallets and transfers]({{ site.baseurl }}/guides/wallets-and-transfers).
Network rules: [Networks]({{ site.baseurl }}/reference/networks).

A wallet looks like:
```json
{"id": 1, "name": "Ledger ETH", "nickname": "🦊 Long-term ETH", "display_name": "🦊 Long-term ETH",
 "kind": "onchain", "provider": "Ledger", "network": "ethereum", "network_name": "Ethereum",
 "address": "0x742d…f44e", "notes": "",
 "colors": {"primary": "#3353cc", "secondary": "#5f33cc", "primary_is_default": true,
            "secondary_mode": "auto", "scheme": "analogous"},
 "tags": ["long-term"], "system_tags": ["kind:onchain", "network:ethereum", "coin:eth", "…"],
 "archived": false, "holdings": [{"symbol": "ETH", "amount": "1.25"}],
 "created_at": "…", "updated_at": "…"}
```

| Endpoint | Notes |
|---|---|
| `GET /api/wallets` | `?kind=`, `?network=`, `?tag=` (yours or built-in), `?archived=false\|true\|all` (default false), `?sort=custom\|name\|created` (custom = your order, then by name) |
| `POST /api/wallets` | `name` and `kind` required; `nickname, provider, network, address, notes, color_primary, color_secondary, color_secondary_mode (auto\|custom), color_scheme (analogous\|complementary\|triadic\|shade), tags` |
| `PATCH /api/wallets/{id}` | Any of the above plus `archived`; only sent fields change, `null` clears |
| `DELETE /api/wallets/{id}` | `204` if empty. Holding coins: `409` with `holdings` and `options`, unless `?move_to=<id>` (all or nothing) or `?force=true&confirm_name=<exact name>` |
| `PUT /api/wallets/{id}/holdings/{symbol}` | `{"amount": "1.25"}` as text; `"0"` removes it. Answers `{wallet_id, symbol, amount}` |
| `GET /api/holdings/summary` | `[{symbol, total, wallets}]`; `?include_archived=true` |
| `GET /api/meta/networks` | Known networks, coin → networks table, kinds, color schemes, tag limit |
| `PUT /api/me/wallet-order` | `{"wallet_ids": [...]}`; your view only |

Errors are `{"detail": "<plain explanation>"}` plus extra fields where useful (`field`,
`holdings`, `options`, `problems`).

## Transfers
| Endpoint | Notes |
|---|---|
| `POST /api/transfers` | `{from_wallet_id, to_wallet_id, symbol, amount (text), note?}` → `201` with the transfer and `warnings` |
| `GET /api/transfers` | Newest first; `?limit=` (1-1000), `?before_id=`, `?wallet_id=` |

A transfer: `{id, created_at, from_wallet_id, to_wallet_id, from_wallet_name, to_wallet_name,
symbol, amount, network, simulated: true, label: "Simulated, no real funds move", note, username}`.

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
