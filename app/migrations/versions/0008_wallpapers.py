"""uploaded wallpapers (milestone 8a)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallpapers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("theme_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("file", sa.String(length=80), nullable=False),
        sa.Column("poster", sa.String(length=80), nullable=False),
        sa.Column("mime", sa.String(length=32), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["theme_id"], ["user_themes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file"),
        sa.UniqueConstraint("poster"),
    )
    with op.batch_alter_table("wallpapers", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_wallpapers_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_wallpapers_theme_id"), ["theme_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("wallpapers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_wallpapers_theme_id"))
        batch_op.drop_index(batch_op.f("ix_wallpapers_owner_id"))

    op.drop_table("wallpapers")
