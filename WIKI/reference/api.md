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
| `GET /api/auth/sessions`, `DELETE /api/auth/sessions/{id}`, `POST /api/auth/sessions/revoke-others` | session (your own only) | Built |
| `GET/POST /api/themes`, `GET/DELETE /api/themes/{id}` | session | Built |
| `POST /api/themes/{id}/publish` | `themes.publish` | Built |
| `GET /api/system/status` | `super` | Built |
| `GET/POST /api/users`, `PATCH/DELETE /api/users/{id}` | `users.manage` | Built |
| `GET /api/meta/permissions` | `users.manage` | Built |
| `GET/POST /api/wallets`, `PATCH/DELETE /api/wallets/{id}` | `wallets.view` / `wallets.edit` | Built |
| `PUT /api/wallets/{id}/holdings/{symbol}` | `wallets.edit` | Built |
| `GET /api/wallets/{id}`, `GET /api/holdings/summary`, `GET /api/meta/networks` | `wallets.view` | Built |
| `PUT /api/me/wallet-order` | session | Built |
| `GET/POST /api/transfers` | `wallets.view` / `transfers.create` | Built |
| `GET /api/prices`, `GET /api/prices/supported`, `GET /api/prices/history` | `prices.view` | Built |
| `GET /api/prices/history/settings` / `PUT` | `prices.view` / `prices.manage` | Built |
| `POST /api/coins`, `DELETE /api/coins/{symbol}` | `prices.manage` | Built |
| `GET /api/portfolio` | `wallets.view` + `prices.view` | Built |
| `GET/PUT/PATCH /api/me/preferences` | session | Built |
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
| `POST /api/auth/totp/setup` | none | `{"secret", "otpauth_uri", "qr"}` (`qr`: an SVG QR code as a `data:` URI for an `<img>`). 409 if 2FA is already on. Calling again replaces the pending secret. |
| `POST /api/auth/totp/enable` | `{"code"}` | `{"recovery_codes": [10 codes]}`, shown once. 400 if wrong code or no setup; 409 if already on. Signs out your other sessions. |
| `POST /api/auth/totp/disable` | `{"password"}` | `{"ok": true}`. 403 wrong password (counts toward lockout); 400 if 2FA is off. |
| `POST /api/auth/totp/recovery-codes` | `{"password"}` | A fresh set of 10; the old ones stop working. 403 / 400 as above. |

Walkthrough: [Set up 2FA]({{ site.baseurl }}/guides/set-up-2fa).

## Your sessions
- `GET /api/auth/sessions`: yours, newest first: `{id, created_at, expires_at, source_ip, device, current}`
  (`device` like "Firefox on Linux", from the browser's own description).
- `DELETE /api/auth/sessions/{id}`: sign one out (not the current one: use logout). Others' sessions answer 404.
- `POST /api/auth/sessions/revoke-others`: `{"revoked": n}`.

## Themes
- `GET /api/themes`: `{builtin: [...], custom: [{id, key, name, author, owner, published, mine, colors}], can_publish, max_per_user}`.
- `GET /api/themes/{id}`: the `.ctheme` itself (yours or published).
- `POST /api/themes` `{"content": "<.ctheme text>"}` → 201; 422 with `problems`; 409 at the limit.
- `POST /api/themes/{id}/publish` `{"published": bool}`; `DELETE /api/themes/{id}` (yours).
- Use one: `PATCH /api/me/preferences {"theme": "custom:<id>"}`.

## System
`GET /api/system/status` (`super`): version, uptime, database revision, price source and
last error, history stats and settings, newest backup, listen addresses, and the CLI commands
for root-only tasks.

## Embeds
Needs `embeds.create`; each user sees and changes only their own. Walkthrough:
[Embeds]({{ site.baseurl }}/guides/embeds).

- `GET /api/embeds/meta`: `{enabled, base_url, kinds, items: {key: {default, label, sensitive}}, enable_command}`.
- `GET /api/embeds`: yours, newest first. Each: `{id, name, kind, enabled, expires_at, views,
  last_viewed_at, created_at, options, url, image_url, iframe}`.
- `POST /api/embeds` `{"name", "kind": "portfolio|wallets|prices", "options": {...}, "expires_at"}` → 201.
  409 at 50 each; 422 with `problems` for bad options.
- `PATCH /api/embeds/{id}`: any of `{name, options, enabled, expires_at}` (`options` replaces all of them).
- `POST /api/embeds/{id}/rotate`: a new link; the old one stops working at once.
- `DELETE /api/embeds/{id}` → 204. `GET /api/embeds/{id}/preview.png`: the Discord picture (409 if off or expired).

`options` (unknown keys refused):

| Key | Default | Meaning |
|---|---|---|
| `items` | see below | `{item: bool}` switches |
| `wallet_ids` | `[]` | Only these wallets (empty: all active) |
| `symbols` | `[]` | Only these coins (empty: all) |
| `theme` | `dark` | `dark`, `light`, `terminal`, `template` or `custom:<id>` (yours or published) |
| `fiat` | `usd` | `usd eur gbp jpy cad aud` |
| `allowed_origins` | `[]` | Websites that may frame it: `https://host[:port]`, up to 20 |
| `refresh_seconds` | `300` | 60-3600 |
| `heading` | `""` | Title on the embed (empty: the name) |

Items: `title`, `wallet_names`, `network`, `tags`, `colors`, `coins`, `percent`, `prices`,
`change_24h`, `updated` (on by default); `amounts`, `values` (off, sensitive).

### The embed server
Separate process and port (default `127.0.0.1:8001`). Only `GET`/`HEAD`; anything else is `405`.

| Path | Is |
|---|---|
| `/embed/{token}` | The page (HTML, no JavaScript, `<meta http-equiv=refresh>`, OpenGraph and Twitter card tags). Counts a view. |
| `/embed/{token}.png` | 1200×630 picture (cached 120 s) |
| `/embed/{token}.css` | Theme colours for that embed |
| `/embed-assets/embed.css`, fonts | Shared styles |

Unknown, off, expired, rotated or deleted links, and owners without the permissions, all get
the same plain `404 Not found`.

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

## Prices
Details and behaviour: [Prices]({{ site.baseurl }}/reference/prices).

| Endpoint | Notes |
|---|---|
| `GET /api/prices` | `?symbols=BTC,ETH` (default: all supported), `?fiat=` → `{fiat, prices: [{symbol, name, price, change_24h}], unpriced, as_of, source, attribution, stale, error}`. `503` if no prices exist at all. |
| `GET /api/prices/supported` | `{coins: [{symbol, name, coingecko_id, builtin}], fiats}` |
| `GET /api/prices/history` | `?symbol=`, `?fiat=`, `?hours=` (default 24) → `{rows: [{at, price, kind: candle\|point, …}]}` |
| `GET/PUT /api/prices/history/settings` | See [history settings]({{ site.baseurl }}/reference/prices#history-settings) |
| `POST /api/coins` | `{coingecko_id, symbol?, confirm?}`; `409` with `lookalikes` when the symbol is shared |
| `DELETE /api/coins/{symbol}` | Extra coins only |
| `GET /api/portfolio` | `?fiat=` (default: your preference), `?include_archived=` → `{fiat, total, coins: [{symbol, name, amount, price, change_24h, value}], wallets: [{id, name, display_name, value, unpriced}], unpriced, as_of, source, attribution, stale, error}` |

`GET /api/wallets` adds `value`, `value_fiat`, `unpriced` and `prices_stale` to each wallet,
and `value` to each holding, for people with `prices.view`; `?sort=value` needs that permission.

## Preferences
Yours only; no permission needed. `GET`, `PUT` (replace all; anything left out returns to
its default) or `PATCH` (replace only the top-level keys sent). Limited to 16 KB; unknown
keys are refused.

| Key | Default | Rules |
|---|---|---|
| `theme` | `dark` | `dark`, `light`, `terminal` |
| `fiat` | `usd` | one of the 6 currencies |
| `watchlist` | `[]` | up to 50 symbols, upper-cased, de-duplicated |
| `overview.columns` | all four | `price`, `change_24h`, `holdings`, `value` |
| `overview.sort` | `{by: value, direction: desc}` | `by`: `value`, `name`, `change_24h`, `symbol` |
| `layout.windows` | `[]` | up to 20 `{panel, x, y, w, h, open, z}`, one per panel; panels `wallets overview transfers users audit settings`; x/y 0-10000, w ≥ 120, h ≥ 80, z 0-100 |
| `wallet_order` | `[]` | wallet ids (also set by `PUT /api/me/wallet-order`) |

## Audit
`GET /api/audit?limit=100` (1 to 1000), newest first. `?before_id=` pages; `?q=` searches the
action, user and detail (case-insensitive). Read-only: there is no way to edit or delete entries through the API.

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
