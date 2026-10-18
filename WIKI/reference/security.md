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
- **Turning 2FA on** asks for your password again (a stolen session alone can't put someone
  else's authenticator on your account) and signs out your other sessions.
- **Recovery codes:** 10 per user, about 50 bits each, from an alphabet without look-alike
  characters. Stored only as argon2id hashes, deleted when used, replaced as a set.
  They still work if the secret key is lost.
- **Recovery without any of that:** `crypto-helper account <name> 2fa reset` on the VM.
- `super` is told `totp_setup_recommended: true` at login until 2FA is on.
- Passkeys / WebAuthn are planned for once HTTPS is set up ([Roadmap]({{ site.baseurl }}/project/roadmap)).

## Sessions
Each session remembers the address and browser description it started from, so you can
recognise and end sessions in Settings → Account. Random 256-bit token in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` when
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
| Setup token | In memory, plus a 0600 file in the state folder until setup is done. Printed only to an interactive terminal; logs, the journal and pipes get `crypto-helper setup token` instead |
| Discord webhook addresses | Fernet-encrypted; shown and audited only masked (last 4 of id and token) |
| Exchange API keys | Fernet-encrypted (all fields); shown and audited only as a masked label |
| Secret key | Env var, or a 0600 file outside the repo |

## Permissions
Catalog lives in one module: `app/permissions.py`. Endpoints are protected with the
`require_permission("...")` dependency; hiding a button is never the check.
`super` always has every permission, including future ones.

| Permission | Allows |
|---|---|
| `wallets.view` | See wallets, balances, transfer history |
| `wallets.edit` | Create/edit/delete wallets, set balances |
| `wallets.connect` | Add read-only exchange keys (and, from 11c, addresses); link wallets to them (with `wallets.edit`) |
| `prices.view` | See the currency overview |
| `transfers.create` | Create simulated transfers |
| `audit.view` | Read the audit log |
| `users.manage` | Manage users |
| `prices.manage` | Add or remove extra coins; change price history settings |
| `themes.publish` | Publish an uploaded theme for everyone |
| `embeds.create` | Create embed links that show wallet or price data outside the app |
| `console.use` | Run the Console's fixed `crypto-helper` commands |
| `terminal.use` | Open a Terminal (the VM's login prompt). **Only super can grant it.** |
| `services.manage` | Turn services and features on and off; run the self-test |
| `apps.manage` | Choose which apps each account can use; switch apps off for everyone |
| `notifications.send` | Send a notification to one person or everyone |

## Apps
On top of permissions, each window (app) can be switched off per account or for everyone
(except `super`). `require_app(...)` on each endpoint enforces it server-side, next to the
endpoint's own permission check; it can only take access away, never add it. The App manager
follows the same rules as user management below, plus: you can only switch apps you can use
yourself. Catalog: `app/apps.py`. Guide: [App manager]({{ site.baseurl }}/guides/app-manager).

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
| admin | trader + audit.view, users.manage, prices.manage, themes.publish |

Presets only fill in the form. Each user stores an explicit list.

## Audit log
Append-only: time, user, action, detail, source IP. Readable with `audit.view` via `GET /api/audit`.
User events record **who did it** in `username` and the target in `detail`. Actions from the CLI
are recorded with the actor `<cli>`. Never contains passwords, tokens, 2FA secrets or recovery
codes. A username that doesn't look like a valid login name is stored as `<invalid>`,
in case someone typed a password in the wrong field.

Every change is audited except your own display state: layout and preferences, wallet order,
reading or clearing your own notifications, and a test message to your own Discord webhook.
They change nothing for anyone else, and the layout saves constantly. `tests/test_route_audit.py`
keeps that list explicit: a new endpoint that changes something must audit or be added there.

## Server logs
The servers' access logs (the systemd journal) never show embed link tokens or query strings
(where the Terminal's one-time ticket travels): `app/logredact.py` replaces them with `…`.
`tests/test_log_secrets.py` runs both servers as the service does, uses every kind of secret,
and checks none appears in their output.

## Seed phrase and private key guard
Every free-text field on wallets and transfers (name, nickname, provider, address, notes,
each tag, transfer note), and everything others can see (embed names and headings, theme
names, authors and descriptions, wallpaper names, notifications sent to others) is checked, and the request is refused if it looks like:
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

## Embeds
Embed links are the one way data leaves the app without a login, so:
- They're served by a **separate process on its own port**, off by default, that only answers
  `GET`/`HEAD` for embed pages, their stylesheets and pictures. It has no session, no API, and
  its own network allowlist and per-address rate limit.
- The link token is 192 random bits, stored as a SHA-256 hash (lookup) and Fernet-encrypted
  (so its owner can copy it again); never in plain text.
- Each item is a separate switch; **amounts and values start off** and are flagged as
  sensitive in the UI and the audit log. Wallet addresses are never shown.
- At every request the server re-checks: enabled, not expired, owner active and still holding
  `embeds.create` (+ `wallets.view` for wallet data; price items need `prices.view`).
  Every failure is the same 404.
- The page has no JavaScript; every value is escaped. Headers: `Content-Security-Policy:
  default-src 'none'` with `frame-ancestors` = the listed websites (or `'none'` plus
  `X-Frame-Options: DENY`), `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`.
- By default it listens on the web UI's addresses (`BOT_HOST`), under the same rules as the
  web UI; addresses of its own beyond this machine need `BOT_EMBED_ALLOW_PUBLIC`. The
  recommended way to publish it to the internet is a tunnel to `127.0.0.1:8001`, never the
  main port.

## The agent
The only root component that runs all the time, so it's kept small:
- A fixed list of operations (`app/agent/protocol.py`), validated strictly (unknown fields,
  odd characters and oversized requests are refused); it never runs a command it's sent.
- Its socket is in a `root:crypto-helper` 750 folder, mode 660, and every connection's Unix
  user is checked (`SO_PEERCRED`): only root and the service user.
- Sandboxed: no network, no capabilities, read-only system except `/etc`.
- The web app decides who may ask (`services.manage` plus the Services app) and audits every
  request with its outcome; the agent logs who asked. Turning the agent off is CLI only.
- Throwaway test servers (the self-test, the tester) never inherit `BOT_*` settings and get a
  socket path of their own, so a test can never reach the real agent.

## Console and Terminal
Walkthrough: [Console and Terminal]({{ site.baseurl }}/guides/console-and-terminal).
- Both off by default (`BOT_CONSOLE_ENABLED`, `BOT_TERMINAL_ENABLED`, root-owned config, switched
  through the agent); both need 2FA on the account.
- **Console**: command ids map to fixed argument lists (`app/agent/console.py`); the only variable
  is a number of log lines (20-1000). Each runs as a one-off systemd unit (time and output limits).
- **Terminal**: `terminal.use` can only be granted by super. Opening one re-checks the password
  (failures count toward lockout) and an authenticator code (replays refused; recovery codes not
  accepted), at most 10 an hour. The agent starts a one-off unit running the bridge, which makes
  a randomly named socket (root:crypto-helper 660, only root or the service user, one connection,
  then deleted, gone after 30 s unused) and runs `/bin/login -h <client ip>` on a pty: the
  Linux password is checked by PAM. The WebSocket needs a one-time 30-second ticket tied to the
  session that asked, an Origin matching the host, an allowed client network; it re-checks the
  session, account and permission every 30 s and closes when any of them ends. Opens, failed
  attempts and closes are audited; keystrokes are never logged.
- The bridge isn't sandboxed (a login session needs to switch users and run `sudo`); the
  agent itself keeps no capabilities.

## Theme bundles
Zips are treated as hostile: names checked against a fixed pattern before anything is read (no
paths out of the bundle, no links, no encryption), at most 60 files, size and compression-ratio
limits (zip bombs), each file read only up to its declared size. Then every part is checked
like an upload of its own: theme rules, wallpaper conversion, icon PNGs re-encoded to 64×64
(hidden text and metadata dropped). Icons as vector paths may only contain path-drawing
characters. `crypto-helper theme pack` refuses links and any file a bundle may not hold.

## Uploaded wallpapers
Every upload is re-encoded before any browser sees it (`app/wallpapers.py`):
- The type comes from the file's first bytes, never its name or the browser's word; a mismatch
  inside is refused.
- Pictures: Pillow with an image-bomb limit (40 million pixels per frame, checked before
  decoding), then WebP with no metadata (no location, camera, comments).
- Videos: ffmpeg is told the exact input format (`-f mov` / `-f matroska`, never a guess) and
  may only read the local file (`-protocol_whitelist file`): a "video" that is really a playlist
  pointing at other files or URLs reads nothing. Output is a new silent WebM with metadata
  dropped. Time limits on every step; one conversion at a time.
- Error messages are fixed sentences: a decoder's output is never shown.
- Files live in the service's private data folder under random names; served only to their
  owner, or everyone once an admin publishes them. Files left behind (e.g. by a deleted user)
  are removed at start-up. Names are checked for pasted secrets like any free text.

## Database locking
Every request that can write (POST, PUT, PATCH, DELETE) takes SQLite's write lock before doing
anything. Two writes at the same moment then wait for each other briefly instead of one failing
with "database is locked" (a test fires 192 parallel requests to check it).

## Notifications
- Each person reads, marks and deletes only their own; the live stream signs in like any
  request, holds no database session while open, re-checks the session every 30 s and closes
  with `signed-out` when it ends.
- Live pushes go out only after the database commit, never for something rolled back.
- Sending to others needs `notifications.send`, is audited, and refuses text that looks like a
  recovery phrase or private key.
- Admins can't switch off security notifications in the app.
- Automatic security notifications (`app/alerts.py`): new device or address, password changed
  or reset, recovery code used (to the account); lockout and 2FA off (also to admins); a
  Terminal opened (to admins). They never contain a password, code or secret. The device is
  worked out from the browser's user-agent, recorded in the `login.ok` audit entry; it's a hint
  only.
- System health (`app/health.py`) reads through the agent's `status` and `update.check`
  operations (fixed, read-only; `update.check` runs `crypto-helper update --check` as a one-off
  unit and never installs) and holds no database lock while it looks.
- **Discord:** only Discord's own webhook addresses are accepted (so the server can't be pointed
  at another machine), redirects aren't followed, nothing pings anyone (`allowed_mentions` empty),
  and what's sent is the title and short text, never balances. Sending happens in a background
  job from an outbox, with no database lock held during the network call; at most 6 tries, and a
  webhook Discord says is gone (401/403/404) stops at once. The address never appears in logs,
  the audit log or API answers.

## Exchange connections (phase 2)
- Only **read-only** keys. On save and again before every sync, the exchange is asked what the
  key may do (where it can say): a key that can trade or move funds is refused and syncing
  stops. Where an exchange can't say, the person adding it must confirm, and that's recorded.
- Each exchange client contains only the calls needed to read; nothing that could place an
  order or move funds exists in the code to be called by mistake.
- Credentials are Fernet-encrypted, shown only as a masked label (last 4 characters), never
  returned, logged or audited. The form clears them once saved.
- Every call to an exchange happens with no database lock held; each has a time limit.
- Synced balances change only by syncing (no hand edits, no practice transfers).

## Help pages
The Help window shows the wiki from the installed copy. A request names a page id from a list
built at start-up, never a path. Pages are sent as a structure of blocks and plain-text pieces
and built in the browser with element APIs, so nothing in a page can become HTML or script;
links are only wiki pages or `http(s)` addresses (anything else is shown as text), and outside
links open in a new tab with `noopener noreferrer`.

## Running as a service
The installed service runs as a dedicated no-login user inside a systemd sandbox (score
1.2 on systemd's 0-10 exposure scale), can read but not change its config and key, and only
listens on `127.0.0.1` unless you opt in. Details: [Service]({{ site.baseurl }}/reference/service).
Remote access options: [Remote access]({{ site.baseurl }}/guides/remote-access).

## Hard rules
No real funds before phase 4. No exchange key with withdrawal permission, ever. No seed
phrases or private keys, ever. Money is `Decimal`, never `float`.
