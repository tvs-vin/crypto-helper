"""smarter alerts and daily prices (milestone 12a)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("armed", sa.Boolean(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_alerts_user_id"), ["user_id"], unique=False)
    op.create_table(
        "daily_candles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("open", sa.String(length=64), nullable=False),
        sa.Column("high", sa.String(length=64), nullable=False),
        sa.Column("low", sa.String(length=64), nullable=False),
        sa.Column("close", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "day", name="uq_daily_candles_symbol_day"),
    )
    with op.batch_alter_table("daily_candles", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_daily_candles_symbol"), ["symbol"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("daily_candles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_daily_candles_symbol"))
    op.drop_table("daily_candles")
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_alerts_user_id"))
    op.drop_table("alerts")
