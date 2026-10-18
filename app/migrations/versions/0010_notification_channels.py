"""notification channels (Discord) and their outbox (milestone 9b)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "kind", name="uq_channels_user_kind"),
    )
    with op.batch_alter_table("notification_channels", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_notification_channels_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["notification_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("deliveries", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_deliveries_channel_id"), ["channel_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_deliveries_next_attempt_at"), ["next_attempt_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("deliveries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_deliveries_next_attempt_at"))
        batch_op.drop_index(batch_op.f("ix_deliveries_channel_id"))

    op.drop_table("deliveries")
    with op.batch_alter_table("notification_channels", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notification_channels_user_id"))

    op.drop_table("notification_channels")
