"""prices: custom coins, price history (points and candles), app settings (milestone 5)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "custom_coins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("coingecko_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("coingecko_id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_table(
        "price_candles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("coingecko_id", sa.String(length=128), nullable=False),
        sa.Column("fiat", sa.String(length=8), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("start", sa.DateTime(), nullable=False),
        sa.Column("open", sa.String(length=64), nullable=False),
        sa.Column("high", sa.String(length=64), nullable=False),
        sa.Column("low", sa.String(length=64), nullable=False),
        sa.Column("close", sa.String(length=64), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "coingecko_id", "fiat", "interval_minutes", "start", name="uq_price_candles_bucket"
        ),
    )
    with op.batch_alter_table("price_candles", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_price_candles_start"), ["start"], unique=False)

    op.create_table(
        "price_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("coingecko_id", sa.String(length=128), nullable=False),
        sa.Column("fiat", sa.String(length=8), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("price", sa.String(length=64), nullable=False),
        sa.Column("change_24h", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("price_points", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_price_points_at"), ["at"], unique=False)
        batch_op.create_index(
            "ix_price_points_coin_fiat_at", ["coingecko_id", "fiat", "at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("price_points", schema=None) as batch_op:
        batch_op.drop_index("ix_price_points_coin_fiat_at")
        batch_op.drop_index(batch_op.f("ix_price_points_at"))

    op.drop_table("price_points")
    with op.batch_alter_table("price_candles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_price_candles_start"))

    op.drop_table("price_candles")
    op.drop_table("custom_coins")
    op.drop_table("app_settings")
