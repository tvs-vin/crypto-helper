"""live bots: a bot's mode, trading key and order settings; live orders' ids (milestone 13c)

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMN (SQLite does it in place): no table is rebuilt.
    op.add_column("bots", sa.Column("mode", sa.String(8), nullable=False, server_default="paper"))
    # SQLite adds a column with a REFERENCES clause in place (its default is NULL); Alembic
    # only knows how by rebuilding the table, which we don't want for live data. No ON DELETE:
    # deleting a key pauses and unlinks its bots in code.
    op.execute("ALTER TABLE bots ADD COLUMN trading_key_id INTEGER REFERENCES trading_keys (id)")
    op.add_column(
        "bots", sa.Column("order_kind", sa.String(8), nullable=False, server_default="limit")
    )
    op.add_column(
        "bots", sa.Column("protection_pct", sa.String(8), nullable=False, server_default="1")
    )
    op.add_column("bot_orders", sa.Column("client_id", sa.String(48), nullable=True))
    op.add_column("bot_orders", sa.Column("exchange_order_id", sa.String(64), nullable=True))
    op.add_column("bot_orders", sa.Column("sent_at", sa.DateTime(), nullable=True))
    op.add_column("bot_orders", sa.Column("fee_asset", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bot_orders") as b:
        for c in ("fee_asset", "sent_at", "exchange_order_id", "client_id"):
            b.drop_column(c)
    with op.batch_alter_table("bots") as b:
        for c in ("protection_pct", "order_kind", "trading_key_id", "mode"):
            b.drop_column(c)
