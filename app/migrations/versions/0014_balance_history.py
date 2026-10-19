"""balance history: wallet balances and their value over time (milestone 11e)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "balance_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("daily", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("at"),
    )
    op.create_table(
        "balance_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.String(length=64), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["balance_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "wallet_id", "symbol", name="uq_balance_points_snap"),
    )
    with op.batch_alter_table("balance_points", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_balance_points_snapshot_id"), ["snapshot_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_balance_points_wallet_id"), ["wallet_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("balance_points", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_balance_points_wallet_id"))
        batch_op.drop_index(batch_op.f("ix_balance_points_snapshot_id"))
    op.drop_table("balance_points")
    op.drop_table("balance_snapshots")
