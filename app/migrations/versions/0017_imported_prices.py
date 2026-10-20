"""past prices imported from Coinbase: candle source, daily prices per currency (12b)

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_candles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(length=16), nullable=False, server_default="recorded")
        )
    with op.batch_alter_table("daily_candles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("quote", sa.String(length=8), nullable=False, server_default="usd")
        )
        batch_op.drop_constraint("uq_daily_candles_symbol_day", type_="unique")
        batch_op.create_unique_constraint(
            "uq_daily_candles_symbol_quote_day", ["symbol", "quote", "day"]
        )


def downgrade() -> None:
    with op.batch_alter_table("daily_candles", schema=None) as batch_op:
        batch_op.drop_constraint("uq_daily_candles_symbol_quote_day", type_="unique")
        batch_op.execute("DELETE FROM daily_candles WHERE quote != 'usd'")
        batch_op.create_unique_constraint("uq_daily_candles_symbol_day", ["symbol", "day"])
        batch_op.drop_column("quote")
    with op.batch_alter_table("price_candles", schema=None) as batch_op:
        batch_op.drop_column("source")
