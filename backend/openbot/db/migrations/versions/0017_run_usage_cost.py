"""record detailed token usage and estimated cost per run

Revision ID: 0017
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = depends_on = None


def upgrade():
    op.add_column("runs", sa.Column("cache_write_tokens", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("reasoning_tokens", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("cost_usd", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("runs", "cost_usd")
    op.drop_column("runs", "reasoning_tokens")
    op.drop_column("runs", "cache_write_tokens")
