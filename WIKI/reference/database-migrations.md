---
title: Database migrations
---

# Database migrations

Schema changes ship as [Alembic](https://alembic.sqlalchemy.org/) migrations in
`app/migrations/versions/`, so upgrading keeps your data.

## Applying them
- The server applies pending migrations every time it starts.
- Or run them by hand: `crypto-helper db migrate`.
- `crypto-helper account …` commands refuse to run on an out-of-date database and tell you to migrate.

A database made before migrations existed (milestones 1 and 2) has no version table. It's
recognised, marked as the baseline, then upgraded.

## History
| Revision | Milestone | Change |
|---|---|---|
| `0001` | 1-2 | Baseline: `users`, `sessions`, `audit_log` |
| `0002` | 3 | `users.totp_last_step` (replay protection), `recovery_codes` table |
| `0003` | 4 | `wallets`, `holdings`, `transfers` tables |
| `0004` | 5 | `custom_coins`, `price_points`, `price_candles`, `app_settings` |
| `0005` | 6c | `sessions.source_ip`, `sessions.user_agent`, `user_themes` |
| `0006` | 6d | `embeds` (owner, kind, hashed + encrypted link token, options, views, expiry) |
| `0007` | 7a | `users.apps` (apps switched on per account; empty = all) |
| `0008` | 8a | `wallpapers` (uploaded wallpapers: owner, optional theme, kind, files, size, published) |
| `0009` | 9a | `notifications` (per user: category, level, title, text, link, sender, read) |
| `0010` | 9b | `notification_channels` (a person's Discord webhook, encrypted), `deliveries` (the outbox: tries, next try, status) |
| `0011` | 9d | `price_alerts` (per user: coin, currency, above/below/move, value as text, armed, last fired) |
| `0012` | 11a | `connections` (read-only exchange keys, encrypted), `wallet_sources` (where a synced wallet's balances come from, and its sync status) |
| `0013` | 11d | `trades` (the trade log: exchange, account, trade and order IDs, time, base/quote, side, amount, price, total, fee; kept when a wallet is deleted) |
| `0019` | 12d | `bots` (paper-trading bots: owner, plan, limits, status, paper account, state), `bot_orders` (each order: decided for, side, coin, asked, status, fill), `bot_points` (value and buy-and-hold value over time) |
| `0018` | 12c | `backtest_runs` (saved backtests: name, settings, summary, value over time, trades; each person's own) |
| `0017` | 12b | `price_candles.source` (`recorded` or `coinbase`) and `daily_candles.quote` (the currency; unique per coin, currency and day): past prices imported onto the charts |
| `0016` | 12a | `alerts` (portfolio, wallet, drift and trend alerts: kind, params, state, armed) and `daily_candles` (daily USD prices per coin from Coinbase) |
| `0015` | 12a | `users.must_change_password`, `users.require_2fa` (account rules) and `users.onboarding` (walkthrough progress) |
| `0014` | 11e | `balance_snapshots` (when; `daily` once compacted) and `balance_points` (per snapshot, wallet and coin: amount and its value in each currency; deleted with the wallet) |

## Adding one (developers)
1. Change `app/models.py`.
2. Generate the migration, numbering it after the last one:
   ```bash
   .venv/bin/alembic revision --autogenerate --rev-id 0006 -m "what changed"
   ```
3. Read the generated file and fix anything Alembic guessed wrong.
4. Add it to the history table above.
5. `pytest` fails (`test_migrations_build_exactly_the_models`) if the models and migrations
   ever disagree.

SQLite can't alter most column definitions in place, so migrations use Alembic's batch mode
(which rebuilds the table). Before a risky migration, take a `crypto-helper db backup`.
