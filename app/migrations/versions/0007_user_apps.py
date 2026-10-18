"""apps switched on per account (milestone 7a)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL = every app, so existing accounts keep everything they had.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("apps", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("apps")
