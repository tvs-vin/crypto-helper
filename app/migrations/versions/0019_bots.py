"""paper-trading bots: bots, their orders, their value over time (milestone 12d)

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_reason", sa.String(length=200), nullable=True),
        sa.Column("account", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("bots", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bots_user_id"), ["user_id"], unique=False)
    op.create_table(
        "bot_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_for", sa.Date(), nullable=True),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("requested", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("filled_at", sa.DateTime(), nullable=True),
        sa.Column("price", sa.String(length=64), nullable=True),
        sa.Column("units", sa.String(length=64), nullable=True),
        sa.Column("value", sa.String(length=64), nullable=True),
        sa.Column("fee", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("bot_orders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bot_orders_bot_id"), ["bot_id"], unique=False)
    op.create_table(
        "bot_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("value", sa.String(length=64), nullable=False),
        sa.Column("benchmark", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("bot_points", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bot_points_bot_id"), ["bot_id"], unique=False)


def downgrade() -> None:
    for table in ("bot_points", "bot_orders", "bots"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            col = "user_id" if table == "bots" else "bot_id"
            batch_op.drop_index(batch_op.f(f"ix_{table}_{col}"))
        op.drop_table(table)
