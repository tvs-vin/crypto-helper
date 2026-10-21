"""saved backtests (milestone 12c)

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("series", sa.JSON(), nullable=False),
        sa.Column("trades", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("backtest_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_backtest_runs_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("backtest_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_backtest_runs_user_id"))
    op.drop_table("backtest_runs")
