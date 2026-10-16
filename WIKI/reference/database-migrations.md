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
