"""embed links (milestone 6d)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embeds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_encrypted", sa.String(length=255), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.Column("last_viewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("embeds", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_embeds_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_embeds_token_hash"), ["token_hash"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("embeds", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_embeds_token_hash"))
        batch_op.drop_index(batch_op.f("ix_embeds_owner_id"))

    op.drop_table("embeds")
