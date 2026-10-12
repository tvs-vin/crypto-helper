# Crypto bot: specification and build order

## 1. Goal
A self-hosted web app that makes crypto easier for its owner: first a dashboard (wallets, balances, prices, users), later a trading bot. It is built in phases so that money is never at risk before the owner understands the system and the safety rails are proven.

The owner is new to crypto. Their original feature list is in section 4; where something in it needs a correction or a safer shape, the corrections are already folded in below. If new requests have the same problem, say so first.

## 2. Glossary (explain these to the owner in plain words when relevant)
- **Exchange account** (Coinbase, Kraken, ...): the exchange holds the coins; the app talks to it with an **API key**.
- **Self-custody wallet** (MetaMask, Ledger, ...): coins live on the blockchain and a **private key** (seed phrase) controls them. Whoever has the key has the coins; transfers are irreversible.
- **Public address**: safe to share; lets anyone *view* a wallet's balance. No secrets involved.
- **API key permissions**: read-only (view), trade (buy/sell), withdraw (move coins out). This app never uses withdraw.
- **Network**: sending a coin on the wrong network (e.g. Ethereum vs Solana) loses it. Always confirm network and address.
- **Swap/trade vs transfer**: a transfer moves the same coin between wallets; converting one coin to another is a trade with fees and slippage.
- **Paper trading**: simulated trading with fake balances against real prices.
- **Slippage and fees**: the real price you get differs from the quote; both eat profit and must be in every backtest.

## 3. Phases
| Phase | Scope | Money at risk |
|---|---|---|
| 1 | Dashboard: auth, users/permissions, wallets (manual/paper balances), simulated transfers, price overview, web UI | None |
| 2 | Real data, read-only: exchange read-only API keys (encrypted at rest), public addresses for on-chain balances, automatic balance sync | None (read-only) |
| 3 | Trading engine: strategy interface, backtester, paper trading, risk rules, kill switch, order/P&L history, notifications | None (paper) |
| 4 | Live: tiny real positions with trade-only keys; real transfers prepared by the app and approved on a hardware wallet | Small, capped |

Only phase 1 is specified in detail. Re-plan with the owner before starting each later phase.

## 4. Owner's original requirements (phase 1)
1. Login system, only reachable through protected measures but still secure on its own.
   - Multiple users with different permission levels and per-feature access, managed from a user management panel in settings.
   - A root user named `super` with every permission.
2. Wallet management: multiple wallets on a homepage, see what each holds, easy transfers between wallets, sort by currency type.
3. Overview panel of currencies and their values, customizable.
4. Web UI, ideally a tiling windowed desktop-like layout, with theming support.
5. More to be decided later.

### Corrections already applied
- **Transfers are simulated (bookkeeping only) in phase 1.** Real transfers need withdrawal keys or private-key signing, which is where funds get lost. Real transfers arrive in phase 4 with hardware-wallet approval. The UI must label phase-1 transfers "Simulated, no real funds move".
- **Viewing balances is safe** (read-only keys, public addresses), so it comes in phase 2.
- **Permissions split by risk**, not just by feature (see 5.2).
- **Added:** audit log, 2FA, lockout, one-time setup token. The owner did not ask for these but multi-user plus money needs them.
- The dashboard alone is not a trading bot. The trading engine is phase 3.

## 5. Phase 1 requirements

### 5.1 Authentication
- First launch: if no users exist, the server generates a one-time **setup token**, prints it to the server console, and `POST /api/setup` requires it. Setup creates the `super` user with a chosen password (min 12 characters). No default password, ever. Setup is impossible once any user exists (handle the race with the unique constraint, return 409).
- Passwords hashed with argon2id (argon2-cffi). Verify against a dummy hash when the username does not exist so timing does not reveal valid usernames.
- Login lockout: 5 failed attempts locks the account for 15 minutes. Failures and lockouts are audited.
- Sessions are server-side: random token in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` when `BOT_COOKIE_SECURE=true`, which must be on behind HTTPS). Only a SHA-256 hash of the token is stored. 12-hour expiry. Logout deletes the session. Changing a password revokes the user's other sessions. Deactivating or deleting a user revokes all their sessions.
- CSRF: every non-GET request under `/api` must carry `X-Requested-With: fetch`, otherwise 403. No CORS.
- TOTP 2FA (pyotp): enrol (generate secret, show `otpauth://` URI, confirm with a code), login requires a code once enabled, disabling requires the password. Offer enrolment for `super` at first login.
- Security headers on all responses: strict CSP (`default-src 'self'`, no inline script or style), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.

### 5.2 Users and permissions
Permission catalog (single module, easy to extend):

| Permission | Allows |
|---|---|
| `wallets.view` | see wallets, balances, transfer history |
| `wallets.edit` | create/edit/delete wallets and set balances |
| `prices.view` | see the currency overview |
| `transfers.create` | create (simulated) transfers |
| `audit.view` | read the audit log |
| `users.manage` | manage users |

Presets for the UI: `viewer` (wallets.view, prices.view), `trader` (viewer + wallets.edit, transfers.create), `admin` (trader + audit.view, users.manage). Users store an explicit permission list; presets only fill the form.

Rules (all enforced server-side, all tested):
- `super` has every permission, always, including future ones. It cannot be edited, deactivated, demoted or deleted, and the name `super` is reserved. Creating a second root is impossible.
- Usernames: lowercase `[a-z0-9_.-]`, 3 to 32 characters.
- **No privilege escalation:** an actor can only *add* permissions they hold themselves; they can only edit or delete users whose permissions are a subset of their own; nobody edits their own permissions or active flag.
- Anything that changes a user (create, permission change, deactivate, password reset, delete) is audited.
- Per-user preferences (theme, layout, watchlist, columns, fiat) need no permission: users only change their own.

### 5.3 Wallets and holdings
- Wallet: name (unique), kind (`exchange` | `onchain` | `paper`), provider/chain label (free text, e.g. "Coinbase", "Ethereum"), optional public address, notes. **No credentials stored in phase 1.**
- Holdings: (wallet, symbol, amount). Amounts are `Decimal` stored as strings, 18 decimal places max, never negative. Setting an amount to 0 removes the holding.
- Homepage Wallets panel: all wallets with their holdings; toggle **group by wallet / group by currency**; filter by wallet kind; sort by name or value.
- Symbols: uppercase `[A-Z0-9]{2,10}`.

### 5.4 Simulated transfers
- `POST /api/transfers` moves a tracked amount between two wallets: different wallets, positive amount, sufficient balance, single database transaction, audited, stored in a transfers table flagged `simulated`.
- UI shows a permanent "Simulated, no real funds move" label on the panel and on each history row.

### 5.5 Prices and overview
- Price provider interface with two implementations: **CoinGecko** (`/api/v3/simple/price`, free tier, 60-second server-side cache, serve stale data with a `stale: true` flag on failure) and a deterministic **mock** (`BOT_PRICE_PROVIDER=mock`) used by tests.
- Symbol allowlist mapping to CoinGecko ids (start: BTC, ETH, SOL, ADA, XRP, DOGE, LTC, DOT, AVAX, LINK, USDT, USDC, BNB, BCH, XLM, ATOM, TRX, SHIB). Unknown symbols are reported back, not an error. Fiat allowlist: usd, eur, gbp, jpy, cad, aud.
- One source of truth for displayed prices; show the source and "as of" time.
- Overview customization (per user): watchlist, visible columns (price, 24h change, holdings, value), fiat currency, sort order.

### 5.6 Preferences
- `GET/PUT /api/me/preferences`, validated with strict models and size limits: theme (`dark` | `light` | `terminal`), fiat, watchlist (max 50), columns, window layout (max 20 windows; x, y, w, h bounded; open flag).

### 5.7 Audit log
- Append-only table: time, user id, username, action, detail, source IP. Never records passwords, tokens or secrets. Events: setup, login ok/fail/lockout, logout, password change, 2FA enable/disable, user create/update/delete, wallet create/edit/delete, holding change, transfer.
- `GET /api/audit?limit=` requires `audit.view`.

### 5.8 Web UI
- Same origin, served by FastAPI. First visit shows the setup screen if needed, otherwise the login screen (with a 2FA field when required).
- **Desktop-style window manager:** each feature is a self-contained panel in a draggable, resizable window with focus/z-order, close, and a taskbar or menu to reopen. A **Tile** button arranges open windows into a grid. Layout is saved per user via preferences. (Real tiling can come later; the panel abstraction must make that easy.)
- **Panels, each gated by its permission:** Wallets, Overview, Transfers, Users, Audit, Settings (theme, password, 2FA).
- **Theming:** CSS variables only; three themes at the start (dark, light, terminal); switching is instant and saved per user.
- Safety: all dynamic data rendered through `textContent` / element APIs. Mobile layout is not a goal yet but nothing should break at narrow widths.

## 6. API surface (phase 1)
| Method and path | Permission |
|---|---|
| `GET /api/setup/status`, `POST /api/setup` | none (setup token required to create) |
| `POST /api/auth/login`, `POST /api/auth/logout` | none / session |
| `GET /api/auth/me` | session |
| `POST /api/auth/password` | session |
| `POST /api/auth/totp/setup`, `/enable`, `/disable` | session |
| `GET/POST /api/users`, `PATCH/DELETE /api/users/{id}`, `GET /api/meta/permissions` | `users.manage` |
| `GET/POST /api/wallets`, `PATCH/DELETE /api/wallets/{id}` | `wallets.view` / `wallets.edit` |
| `PUT /api/wallets/{id}/holdings/{symbol}` | `wallets.edit` |
| `GET/POST /api/transfers` | `wallets.view` / `transfers.create` |
| `GET /api/prices`, `GET /api/prices/supported` | `prices.view` |
| `GET/PUT /api/me/preferences` | session |
| `GET /api/audit` | `audit.view` |

## 7. Data model (phase 1)
`users` (username, password_hash, permissions JSON, is_super, is_active, totp_secret, totp_enabled, failed_logins, locked_until, preferences JSON) · `sessions` (token_hash, user_id, created_at, expires_at) · `wallets` · `holdings` · `transfers` · `audit_log`.

Note for phase 2: TOTP secrets and exchange API keys must be encrypted at rest with a key from the environment (not in the repo or database). Add this before storing any exchange credential.

## 8. Milestones (stop and report after each)
1. **Skeleton and auth.** App factory, config via env, DB models, setup token flow, login/logout, lockout, sessions, CSRF guard, security headers, `me`, change password. Tests for all of it.
2. **Users, permissions, audit.** Everything in 5.2 and 5.7, with tests for every escalation rule and every denial path.
3. **2FA.** TOTP enrol, login with code, disable. Tests.
4. **Wallets, holdings, simulated transfers.** 5.3 and 5.4 with tests (insufficient balance, same-wallet, negative/oversized amounts, atomicity).
5. **Prices and preferences.** 5.5 and 5.6 with the mock provider in tests, plus one manual check of the real CoinGecko provider.
6. **Web UI.** 5.8. Verify JS syntax (`node --check` on each module), exercise the API from the UI flow, and if a browser is available look at it for real. Be honest in the report about what was and was not visually verified.
7. **Wrap-up.** README (setup, run, test, first-launch steps), `.env.example`, a systemd unit example, SQLite backup instructions.

Definition of done for every milestone: tests pass, nothing sensitive logged, permission checks tested, `CLAUDE.md` Commands section updated, committed.

## 9. Deployment notes (headless VM)
- Run with `uvicorn` bound to `127.0.0.1:8000`. To use the UI from another computer, tunnel it: `ssh -L 8000:127.0.0.1:8000 <vm>` then open `http://localhost:8000`.
- For a permanent setup, put it behind Tailscale (`tailscale serve`) or Cloudflare Access, which also gives HTTPS; then set `BOT_COOKIE_SECURE=true`.
- Run as an unprivileged user under systemd. Back up the SQLite file regularly.
- Never expose the port directly to the internet.

## 10. Ask the owner at the start of the session
1. Do you hold (or plan to hold) funds on **exchanges**, in **self-custody wallets**, or both? Which exchanges and which coins? (Decides the phase 2 design.)
2. Are you comfortable reading and editing Python, or do you want everything explained as we go?
3. What should the bot eventually do first: track and alert, automate regular buys (DCA), or active trading? (Decides phase 3 order.)
4. Is this US-based? (Affects which exchanges are available and how trades must be logged for taxes.)
Record the answers in `CLAUDE.md` under a "Decisions" heading.

## 11. Later phases, parked ideas
- Phase 2: exchange read-only sync, on-chain balances by public address, balance history charts.
- Phase 3: DCA and rebalancing first (simple, low risk), then technical strategies; backtester must include fees and slippage; per-trade and per-day loss limits; kill switch; Telegram or email alerts; trade log with timestamp, pair, side, quantity, price and fee for tax reporting.
- Phase 4: trade-only keys with IP restriction; real transfers via WalletConnect or hardware wallet with address whitelist, network confirmation and a mandatory small test transfer.
- Real tiling window manager; mobile layout.
