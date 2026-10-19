"""trades: the trade log (milestone 11d)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=True),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("account", sa.String(length=64), nullable=False),
        sa.Column("trade_id", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.String(length=100), nullable=True),
        sa.Column("time", sa.DateTime(), nullable=False),
        sa.Column("base", sa.String(length=16), nullable=False),
        sa.Column("quote", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("amount", sa.String(length=64), nullable=False),
        sa.Column("price", sa.String(length=64), nullable=False),
        sa.Column("total", sa.String(length=64), nullable=False),
        sa.Column("fee", sa.String(length=64), nullable=False),
        sa.Column("fee_asset", sa.String(length=16), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wallet_id", "trade_id", name="uq_trades_wallet_trade"),
    )
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_trades_time"), ["time"], unique=False)
        batch_op.create_index(batch_op.f("ix_trades_wallet_id"), ["wallet_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_trades_wallet_id"))
        batch_op.drop_index(batch_op.f("ix_trades_time"))
    op.drop_table("trades")
