"""wallets, holdings and simulated transfers (milestone 4)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("nickname", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("network", sa.String(length=32), nullable=True),
        sa.Column("address", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("color_primary", sa.String(length=7), nullable=True),
        sa.Column("color_secondary", sa.String(length=7), nullable=True),
        sa.Column("color_secondary_mode", sa.String(length=8), nullable=False),
        sa.Column("color_scheme", sa.String(length=16), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "holdings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wallet_id", "symbol", name="uq_holdings_wallet_symbol"),
    )
    with op.batch_alter_table("holdings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_holdings_wallet_id"), ["wallet_id"], unique=False)

    op.create_table(
        "transfers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("from_wallet_id", sa.Integer(), nullable=True),
        sa.Column("to_wallet_id", sa.Integer(), nullable=True),
        sa.Column("from_wallet_name", sa.String(length=64), nullable=False),
        sa.Column("to_wallet_name", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.String(length=64), nullable=False),
        sa.Column("network", sa.String(length=32), nullable=True),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["from_wallet_id"], ["wallets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_wallet_id"], ["wallets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transfers", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_transfers_created_at"), ["created_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_transfers_from_wallet_id"), ["from_wallet_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_transfers_to_wallet_id"), ["to_wallet_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("transfers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transfers_to_wallet_id"))
        batch_op.drop_index(batch_op.f("ix_transfers_from_wallet_id"))
        batch_op.drop_index(batch_op.f("ix_transfers_created_at"))

    op.drop_table("transfers")
    with op.batch_alter_table("holdings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_holdings_wallet_id"))

    op.drop_table("holdings")
    op.drop_table("wallets")
