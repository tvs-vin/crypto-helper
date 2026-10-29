"""live trading foundations: trading keys and each person's cap (milestone 13a)

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trading_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("masked", sa.String(length=160), nullable=False),
        sa.Column("check", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trading_keys_owner_id", "trading_keys", ["owner_id"])
    # Plain ADD COLUMN (SQLite does it in place): the users table is never rebuilt.
    op.add_column("users", sa.Column("live_cap", sa.String(length=40), nullable=True))
    op.add_column("users", sa.Column("live_cap_ceiling", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("live_cap_ceiling")
        batch.drop_column("live_cap")
    op.drop_index("ix_trading_keys_owner_id", table_name="trading_keys")
    op.drop_table("trading_keys")
