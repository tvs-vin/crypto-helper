"""price alerts (milestone 9d)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("coingecko_id", sa.String(length=100), nullable=False),
        sa.Column("fiat", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("value", sa.String(length=40), nullable=False),
        sa.Column("armed", sa.Boolean(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("price_alerts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_price_alerts_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("price_alerts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_price_alerts_user_id"))

    op.drop_table("price_alerts")
