"""sessions remember where they started; uploaded themes (milestone 6c)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_themes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("user_themes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_themes_owner_id"), ["owner_id"], unique=False)

    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_ip", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("user_agent", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("user_agent")
        batch_op.drop_column("source_ip")

    with op.batch_alter_table("user_themes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_themes_owner_id"))

    op.drop_table("user_themes")
