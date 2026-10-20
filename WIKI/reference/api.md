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
| `GET/POST /api/alerts`, `DELETE /api/alerts/{id}`, `GET /api/prices/daily` | `prices.view` (+ `wallets.view` per kind) | Built |
| `GET /api/onboarding`, `POST /api/onboarding/…` | session | Built |
| `GET/PUT /api/server/network`, `POST /api/server/network/confirm` | `super` | Built |
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
| `PUT /api/me/wallet-order` | `wallets.view` | Built |
| `GET/POST /api/transfers` | `wallets.view` / `transfers.create` | Built |
| `GET /api/prices`, `GET /api/prices/supported`, `GET /api/prices/history` | `prices.view` | Built |
| `GET /api/prices/history/settings` / `PUT` | `prices.view` / `prices.manage` | Built |
| `POST /api/coins`, `DELETE /api/coins/{symbol}` | `prices.manage` | Built |
| `GET /api/portfolio` | `wallets.view` + `prices.view` | Built |
| `GET /api/balance-history/portfolio`, `/wallets`, `/wallets/{id}` | `wallets.view` + `prices.view` | Built |
| `GET /api/balance-history/settings` / `PUT` | `prices.view` / `prices.manage` | Built |
| `GET/PUT/PATCH /api/me/preferences` | session | Built |
| `GET /api/audit` | `audit.view` | Built |

Any API request body over 2 MB is refused with `413` before it's read, except the two uploads
(`POST /api/wallpapers`, `POST /api/themes/upload`), which have their own limits.

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

`GET /api/auth/me` returns `id, username, is_super, permissions, totp_enabled, recovery_codes_left, preferences`,
and the [account rules](#account-rules): `restricted` (`null`, `"password"` or `"2fa"`), `requires_2fa`,
`must_change_password`.

## 2FA
| Endpoint | Body | Answer |
|---|---|---|
| `POST /api/auth/totp/setup` | none | `{"secret", "otpauth_uri", "qr"}` (`qr`: an SVG QR code as a `data:` URI for an `<img>`). 409 if 2FA is already on. Calling again replaces the pending secret. |
| `POST /api/auth/totp/enable` | `{"code", "password"}` | `{"recovery_codes": [10 codes]}`, shown once. 400 if wrong code or no setup; 403 if the password is wrong (counts toward lockout); 409 if already on. Signs out your other sessions. |
| `POST /api/auth/totp/disable` | `{"password"}` | `{"ok": true}`. 403 wrong password (counts toward lockout); 400 if 2FA is off; 409 if the account requires 2FA. |
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
- `POST /api/themes/upload` (raw body: a plain `.ctheme` or a bundle) → `201`; `GET /api/themes/{id}/bundle`
  → the bundle (zip). List entries include `wallpaper`, `icons` (count) and `bundle`.
- `POST /api/themes` `{"content": "<.ctheme text>"}` → 201; 422 with `problems`; 409 at the limit.
- `POST /api/themes/{id}/publish` `{"published": bool}`; `DELETE /api/themes/{id}` (yours).
- Use one: `PATCH /api/me/preferences {"theme": "custom:<id>"}`.

## System
`GET /api/system/status` (`super`): version, uptime, database revision, price source and
last error, history stats and settings, balance history stats (`balance_history: {snapshots,
points, newest, oldest}`), newest backup, listen addresses, and the CLI commands
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
Separate process and port (default 8001, on the web UI's addresses). Only `GET`/`HEAD`; anything else is `405`.

| Path | Is |
|---|---|
| `/embed/{token}` | The page (HTML, no JavaScript, `<meta http-equiv=refresh>`, OpenGraph and Twitter card tags). Counts a view. |
| `/embed/{token}.png` | 1200×630 picture (cached 120 s) |
| `/embed/{token}.css` | Theme colours for that embed |
| `/embed-assets/embed.css`, fonts | Shared styles |

Unknown, off, expired, rotated or deleted links, and owners without the permissions, all get
the same plain `404 Not found`.

## Apps
Walkthrough: [App manager]({{ site.baseurl }}/guides/app-manager). `GET /api/auth/me` includes
`apps`: the windows this account can open (`settings` always first).

Every endpoint used by an app answers `403` with the reason (e.g. "The Wallets app is turned
off for your account") when the account can use none of the apps it belongs to:

| App | Endpoints |
|---|---|
| Wallets | `/api/wallets` (all), `/api/holdings/summary`, `/api/meta/networks`, `/api/me/wallet-order`, `/api/portfolio`, `/api/balance-history/wallets` (and `/{id}`) |
| Transfers | `/api/transfers`, `GET /api/wallets`, `GET /api/wallets/{id}` |
| Overview | `/api/prices`, `/api/prices/history`, `/api/portfolio`, `/api/balance-history/portfolio` |
| Audit log | `/api/audit` |
| Users | `/api/users`, `/api/meta/permissions` |
| App manager | `/api/apps` (all) |
| Services | `/api/services` (all) |
| Console | `/api/console/*` |
| Terminal | `/api/terminal/open` (and the WebSocket checks the app too) |

Never switched off: sign-in and sessions, 2FA, `/api/me/preferences`, themes, coins, price
history settings, balance history settings, `/api/prices/supported`, embeds, system status, setup.

App manager (`apps.manage`, and the App manager app):
- `GET /api/apps`: `{apps: [{id, name, description, needs, enabled, can_grant}], core,
  permissions, accounts: [{id, username, is_super, is_active, chosen, status, locked}]}`.
  `chosen` is `"all"` or a list; `status[app]` is `null` (can open it) or the reason it can't.
- `PUT /api/apps/{app}/enabled` `{"enabled": bool}`: on/off for everyone except super.
- `PUT /api/apps/accounts/{user_id}` `{"apps": [...] | "all"}`. 403 for super, yourself, an
  account with permissions you don't hold, or changing an app you can't use; 422 unknown app.

## Services
`services.manage` and the Services app. Walkthrough: [Services]({{ site.baseurl }}/guides/services).
- `GET /api/services`: `{agent: {available, reason?, command?}, services: {web, embed, backups,
  agent: {active, enabled}} | null, embed: {enabled, links}, backup, features, selftest}`.
- `PUT /api/services/features`: any of `{paper_wallets, practice_transfers, practice_prices,
  price_history, balance_history}` as booleans. Applies to everyone, super included.
- `POST /api/services/{embed|backups}/switch` `{"on": bool}`, `POST /api/services/{web|embed}/restart`,
  `POST /api/services/backups/run`: through the agent; `503` with the command to turn it on
  when there's no agent, `502` with the reason when it refuses.
- `POST /api/services/selftest` → `202` (`409` if one is running); `GET /api/services/selftest`:
  `{running, started_at, last: {ok, passed, failed, checks, failures, log, started_by, finished_at}}`.

With a feature off: `POST /api/wallets` with `kind: paper` (or changing a wallet to paper) and
`POST /api/transfers` answer `403` saying so.

## Wallpapers
Settings, so no extra permission. Walkthrough: [Using the desktop]({{ site.baseurl }}/guides/using-the-desktop#wallpaper).
- `GET /api/wallpapers`: `{builtin: [...], uploaded: [...], can_publish, max_per_user, video, accept}`;
  each `{key, name, kind (image|animated|video), url, poster, ...}`. `uploaded` holds yours and
  published ones.
- `POST /api/wallpapers?name=…` with the file as the raw request body
  (`Content-Type: application/octet-stream`) → `201`. `413` too big (60 MB, pictures 25 MB),
  `422` not usable (the reason), `409` at 20, `429` while another upload is being converted,
  `507` server space full (2 GB).
- `GET /api/wallpapers/{id}`, `/file`, `/poster`: yours, published, or (for super) any; `404`
  otherwise. Files are served with `Cache-Control: private, immutable`.
- `PATCH /api/wallpapers/{id}` `{name?, published?}` (publishing needs `themes.publish`);
  `DELETE /api/wallpapers/{id}` (its owner, or super).

## Console and Terminal
Walkthrough: [Console and Terminal]({{ site.baseurl }}/guides/console-and-terminal).
- `GET /api/console/commands` (`console.use`): `[{id, description}]`.
- `POST /api/console/run` `{"command": id, "lines"?: 20-1000}` → `{command, exit_code, output}`.
  `403` without 2FA; `409` while the Console is off; `422` for anything not in the list.
- `POST /api/terminal/open` `{"password", "code", "cols", "rows"}` (`terminal.use`) → `{"ticket"}`.
  `403` without 2FA or with a wrong password/code; `429` after 10 in an hour; `409` while off.
- `WS /api/terminal/ws?ticket=…`: binary frames are terminal bytes both ways; a text frame
  `{"resize": [cols, rows]}` resizes. Close codes: `4403` wrong network or Origin, `4401` bad,
  used or expired ticket (or not the session that asked), `4404` session gone.

## Notifications
Yours only, no permission needed, except sending. Walkthrough: [Notifications]({{ site.baseurl }}/guides/notifications).
- `GET /api/notifications?unread=&limit=&before=` (limit 1-200, default 50; `before` an id, for
  paging) → `{items: [{id, category, level, title, body, link, sender, created_at, read}], unread}`.
  `category`: `security|system|prices|messages`; `level`: `info|warning|critical`; `link` a window
  name or null; `sender` a username or `system`.
- `POST /api/notifications/read` `{"ids": [...]}` (left out or null = all) → `{unread}`.
- `DELETE /api/notifications/{id}` → `204` (`404` if not yours); `DELETE /api/notifications` clears
  the read ones.
- `GET /api/notifications/stream`: server-sent events. `event: notification` with the item above,
  `event: signed-out` when the session ends (checked every 30 s); a comment every 20 s keeps it
  open. `401` without a session.
- `GET /api/notifications/recipients` and `POST /api/notifications/send` (`notifications.send`):
  `{"to": user_id | "all", "title" (1-120), "body"? (≤1000), "level"?, "link"?}` → `201
  {sent, to}`. `sent` leaves out anyone who turned Messages off. `404` unknown person, `422`
  bad link/level or text that looks like a recovery phrase or key.

### Discord
- `GET /api/notifications/channels` → `{"discord": {kind, label, created_at, last_ok_at,
  last_error, failures} | null}`. `label` is masked (`Discord webhook …1234 (token …abcd)`):
  the address is never returned.
- `PUT /api/notifications/channels/discord` `{"url"}`: only
  `https://(discord.com|discordapp.com|ptb.discord.com|canary.discord.com)/api/webhooks/<id>/<token>`;
  anything else `422`. Replaces an earlier one.
- `POST /api/notifications/channels/discord/test`: posts a test message now. `502` with the
  reason when Discord refuses or can't be reached; `404` with no webhook.
- `DELETE /api/notifications/channels/discord` → `204`.

## Users
- `GET /api/users`: list users. Never returns hashes or 2FA secrets. `locked` is true during a lockout.
- `POST /api/users`: `{"username", "password", "permissions": [...], "is_active": true,
  "must_change_password": false, "require_2fa": false}`.
- `PATCH /api/users/{id}`: any of `{"permissions": [...], "is_active": bool, "password": "...",
  "must_change_password": bool, "require_2fa": bool}`.
  A password reset also clears a lockout. Deactivating or resetting a password signs the user out everywhere.
  Users carry `must_change_password` and `require_2fa` (always true for super).
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

### Price alerts
Yours only; `prices.view` and the Overview or Alerts app. Guide: [Price alerts]({{ site.baseurl }}/guides/prices-and-portfolio#price-alerts).
- `GET /api/price-alerts` → `{alerts: [{id, symbol, fiat, kind, value, text, state, last_fired_at,
  created_at, price, change_24h}], max}`. `state`: `armed`, `fired` (waits for the price to cross
  back), `waiting` (was already true when added). `price`/`change_24h` are now (null when prices
  aren't available or practice prices are on).
- `POST /api/price-alerts` `{symbol, fiat, kind: above|below|move, value}` → `201`. `value` is
  text (a price, or 0.1-1000 percent for `move`); a JSON number, unknown coin or currency is `422`;
  `409` at 50.
- `DELETE /api/price-alerts/{id}` → `204` (`404` if not yours). Both are audited.

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
| `scale` | `100` | Display scale in percent: 75-150 in steps of 5 (a browser may override it for itself) |
| `wallpaper` | none | `{source, fit, dim, blur, motion}`: `source` is `none`, `builtin:<name>`, `user:<id>` or `theme`; `fit` `cover\|contain\|center\|tile`; `dim` 0-80; `blur` 0-20; `motion` `auto\|still` |
| `layout.windows` | `[]` | up to 20 `{panel, id, x, y, w, h, open, minimized, maximized, z, state}`; `panel` is any app or `settings`; `id` is the panel name for its first window and `panel:2` … `panel:4` for more (Overview, Wallets, Transfers, Audit log allow 4, the rest 1; no `id` = the first); each id once; `state` is the window's own settings, up to 8 plain values (keys `a-z_`, text ≤ 40 characters), e.g. Overview's `{fiat, coin, hours}`; x/y 0-10000, w ≥ 120, h ≥ 80, z 0-100 |
| `notifications.channels` | in-app on, Discord off | `{security\|system\|prices\|messages: {inapp, discord}}` (admins always get security in the app) |
| `notifications.quiet_from` / `quiet_to` | none | `HH:MM`; Discord waits until `quiet_to` (critical ones don't wait) |
| `notifications.utc_offset_minutes` | `0` | -840 to 840: the time zone quiet hours are in (the web app sends the browser's) |
| `wallet_order` | `[]` | wallet ids (also set by `PUT /api/me/wallet-order`) |

## Connections and syncing (phase 2)
Walkthrough: [Exchange connections]({{ site.baseurl }}/guides/exchange-connections). All need the
Wallets app.
- `GET /api/sync/exchanges` (`wallets.connect`) → `[{id, name, guide, confirm_text, fields:
  [{name, label, secret, help, multiline}]}]`: the exchanges this install offers.
- `GET /api/connections` (`wallets.connect`) → `[{id, kind, exchange, label, masked,
  check_summary, checked_at, created_by, created_at, wallets: [{id, name}]}]`. Never the key.
- `POST /api/connections` `{kind, label, credentials: {field: value}, confirm_read_only?}` → `201`.
  The key is checked with the exchange first: `422` if it can trade or move funds (or the
  exchange rejects it); `409` `{detail: {message, confirm}}` when the exchange can't say what it
  may do (send again with `confirm_read_only: true`).
- `PATCH /api/connections/{id}` `{label}`; `POST /api/connections/{id}/check` (ask the exchange
  again; `422` if it's no longer read-only); `DELETE /api/connections/{id}` (`409` while
  wallets sync from it).
- `PUT /api/wallets/{id}/source` (`wallets.connect` and `wallets.edit`) `{kind: "manual"}`,
  `{kind: "exchange", connection_id}` (exchange wallets), or `{kind: "onchain", addresses?: [...],
  xpub?, script?: auto|wpkh|tr|sh-wpkh|pkh}` (on-chain wallets on a syncable network; no
  addresses means the wallet's own; `xpub` is Bitcoin only). `422` for an address of another
  network, an extended *private* key (explained, never echoed), or an unsupported network.
- `GET`/`PUT /api/sync/chains` (`wallets.connect`): `{esplora_url, rpc: {network: url}}` (your own
  data servers; `https://`, or `http://` only to a private address); `GET` adds the `defaults`.
- `POST /api/wallets/{id}/sync` (`wallets.edit`): sync now → `{ok, changes, error, sync}`;
  `409` if the wallet isn't synced.
- `GET`/`PUT /api/sync/settings` (`wallets.connect`): `{enabled, interval_minutes}` (5-1440).
- Wallets (`GET /api/wallets`, `/api/wallets/{id}`) carry `sync`: null, or `{kind,
  connection_id, label, info, last_ok_at, last_try_at, last_error, failures, untracked: [{asset,
  amount}]}` (`info` for an xpub: `{used_addresses, types}`). `GET /api/meta/networks` adds
  `syncable`: the networks that can sync from addresses. A synced wallet's balances can't be set by hand (`409`) or used in practice
  transfers (`409`); deleting it needs no moving.

## Trade log
Walkthrough: [Trade log]({{ site.baseurl }}/guides/trade-log). `wallets.view` and the Trade log app.
- `GET /api/trades?wallet_id=&asset=&since=&until=&side=&limit=&before_id=` → `{trades: [{id,
  wallet_id, exchange, exchange_name, account, trade_id, order_id, time, base, quote, side,
  amount, price, total, fee, fee_asset}], total}`. Newest first; `since`/`until` are UTC dates
  (`until` takes the whole day); `asset` matches base or quote; `limit` up to 500.
- `GET /api/trades/formats` → `[{id, name, note}]`: `generic`, `koinly`, `cointracker`,
  `coinledger`, `turbotax`.
- `GET /api/trades/export?format=…` (same filters) → a CSV download
  (`trades-<format>-<date>.csv`), oldest first; audited (`trades.export`). `422` unknown format,
  `413` over 200,000 trades.
- Trades are imported by syncing (Sync now, or hourly in the background); a wallet's `sync` adds
  `trades_at` and `trades_error`. One connection syncs one wallet (`409` for a second).

## Alerts
Yours only; `prices.view`, the Alerts app, and per kind: `portfolio` and `drift` also
`wallets.view`, `wallet` `wallets.view` (no `prices.view` needed for the change itself). Guide:
[Alerts]({{ site.baseurl }}/guides/alerts).
- `GET /api/alerts` → `{alerts: [{id, kind, params, text, state: armed|fired, note, side,
  last_fired_at, created_at}], max, kinds (the ones you may add), synced_wallets: [{id, name}],
  daily: {symbol: {first, last, days}}, coins}`.
- `POST /api/alerts` `{kind, params}` → `201` (audited `alerts.create`). `params` by kind:
  - `portfolio`: `{condition: above|below|move, value, fiat, window: 24h|7d}` (`value` text: an
    amount, or a percent 0.1-1000 for `move`);
  - `wallet`: `{wallet_id | null (any synced), direction: any|up|down, min_value | null, fiat}`;
  - `drift`: `{targets: {SYMBOL: percent}, threshold}` (targets add up to 100 or less; threshold
    1-50 points);
  - `trend`: `{symbol, signal: ma_cross|drawdown, days: 5-365, direction: up|down|either,
    percent (drawdown, 1-90)}`.
  `422` with the reason for anything out of range, an unknown coin or a wallet that doesn't sync;
  `403` for a kind your permissions don't allow; `409` past 50.
- `DELETE /api/alerts/{id}` → `204` (audited `alerts.delete`; `404` if not yours).
- `GET /api/prices/daily?symbol=&days=` (`prices.view`, Alerts or Overview app) → `{symbol,
  rows: [{day, open, high, low, close}]}`: daily USD prices from Coinbase, oldest first.
- Notifications carry detail markers in storage; the API and the app always show the full text,
  Discord only the details allowed in `preferences.notifications.discord_details` (any of
  `amounts`, `values`, `wallets`, `allocation`).

## Account rules
An account that must choose a new password (`must_change_password`) or must turn on 2FA
(`require_2fa`, and super always) gets `403 {"detail", "restricted": "password" | "2fa"}` from
everything except: `GET /api/auth/me`, `POST /api/auth/password` (which clears the rule; the
new password must differ), `POST /api/auth/totp/setup|enable|disable|recovery-codes`,
`GET/DELETE /api/auth/sessions…`, sign-out, `GET /api/notifications/stream` and
`GET /api/onboarding`. Walkthrough: [First steps]({{ site.baseurl }}/guides/first-steps#account-rules).

## Onboarding
Walkthrough: [First steps]({{ site.baseurl }}/guides/first-steps). Any signed-in account.
- `GET /api/onboarding` (also while a rule is pending) → `{restricted, show, account: [{id, title,
  done, required?}], server: [...] | null, done, total}`. `server` is super's server steps
  (`key_backup`, `network`, `services`, `data`, `people`); `account` only has the steps the
  account's permissions allow. `show`: open the walkthrough at sign-in.
- `POST /api/onboarding/steps/{step}`: tick a step that's done by finishing it (`welcome`,
  `personalise`, `notifications`, `tour`; super also the server steps, audited as
  `onboarding.server`; `403` for anyone else). The others tick themselves from the data.
- `POST /api/onboarding/finish` / `restart`: don't open / open the walkthrough at sign-in.

## Server setup
super only (`403` otherwise). Walkthrough: [First steps]({{ site.baseurl }}/guides/first-steps#changing-where-it-listens).
- `GET /api/server/network` → `{hosts, port, allowed_networks, addresses: [{address,
  interface, kind, listening}], you: {client_ip, via}, agent, pending, seconds_left,
  confirm_within, boot, manual: {file, then, agent}}`. `boot` changes on every server start.
- `PUT /api/server/network` `{"hosts": [...], "allowed_networks": [...]}` (audited
  `server.network`): `422` for `0.0.0.0`/`::`, no `127.0.0.1`, no `127.0.0.0/8`, a `/0`
  network, an address that isn't this machine's, dropping the address you're using, or
  networks that don't include your browser's address; `503` without the agent. The agent
  writes `BOT_HOST`, `BOT_ALLOWED_NETWORKS` and `BOT_ALLOW_REMOTE_BIND`, restarts the web UI
  (and the embed server if on) and answers `{hosts, allowed_networks, confirm_within}`.
- `POST /api/server/network/confirm` (audited `server.network.confirm`): keep it. Must come from
  the restarted server (the page waits for `boot` to change); without it, the agent restores the
  old file after `confirm_within` seconds (120) and restarts again. `409` if there's nothing to
  confirm or it's too early.

## Balance history
Walkthrough: [Balance history]({{ site.baseurl }}/guides/balance-history). Reading needs
`wallets.view` and `prices.view`. `fiat` defaults to your preferred currency (`422` for an
unknown one); `days` is 1-36500 (default 30). Rows are oldest first; `at` is UTC.
- `GET /api/balance-history/portfolio?days=&fiat=&include_archived=&most=` (Overview app) →
  `{fiat, days, change, rows: [{at, value, unpriced}]}`: the combined value of today's wallets
  (archived ones only with `include_archived=true`; a wallet counts from its creation).
  `change` is `null` (fewer than two rows) or `{from, to, amount, percent}` (exact; `percent` is
  `null` from zero). `most` (2-5000, default 1000) thins the rows evenly, keeping the first and
  last.
- `GET /api/balance-history/wallets/{id}?days=&fiat=&most=` (Wallets app) → `{wallet_id, fiat,
  days, change, rows: [{at, value, unpriced, coins: {symbol: amount}}]}`. `404` unknown wallet.
- `GET /api/balance-history/wallets?days=&fiat=&most=` (Wallets app) → `{fiat, days, wallets:
  {"<id>": [{at, value}]}}`: every wallet at once for the cards' trends (`most` 2-500, default 60).
- `GET /api/balance-history/settings` (`prices.view`) → `{settings: {enabled, interval_minutes,
  detail_days, keep_days}, stats: {snapshots, points, newest, oldest}}`.
- `PUT /api/balance-history/settings` (`prices.manage`): the whole `settings` object
  (`interval_minutes` 5-1440, `detail_days` 1-365, `keep_days` 0-36500 with 0 = forever);
  audited (`balances.history_settings`); `422` for anything out of range or unknown.

## Help
Anyone signed in; no permission needed. Walkthrough: [Help]({{ site.baseurl }}/guides/using-the-desktop#help).
- `GET /api/help` → `{sections: [{id, title, pages: [{id, title}]}]}`.
- `GET /api/help/page?id=guides/notifications` → `{id, title, section, blocks}`. `id` must be one
  of the listed pages (`404` otherwise; it's never used as a path). `blocks` are
  `{t: h|p|quote|code|table|ul|ol, ...}`; text is a list of `[kind, text, target?]` pieces with
  `kind` `text|strong|em|code|link`, and a link's target is `{page, anchor}` or `{url}`.
- `GET /api/help/search?q=` (1-100 characters) → `{results: [{id, title, anchor, snippet}]}`.

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
