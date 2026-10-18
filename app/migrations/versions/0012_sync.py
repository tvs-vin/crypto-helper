"""connections and wallet sources (milestone 11a)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("masked", sa.String(length=160), nullable=False),
        sa.Column("check_summary", sa.String(length=200), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "wallet_sources",
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("watch_encrypted", sa.Text(), nullable=True),
        sa.Column("watch_masked", sa.String(length=200), nullable=True),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("last_try_at", sa.DateTime(), nullable=True),
        sa.Column("last_ok_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("untracked", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("wallet_id"),
    )
    with op.batch_alter_table("wallet_sources", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_wallet_sources_connection_id"), ["connection_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("wallet_sources", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_wallet_sources_connection_id"))
    op.drop_table("wallet_sources")
    op.drop_table("connections")
