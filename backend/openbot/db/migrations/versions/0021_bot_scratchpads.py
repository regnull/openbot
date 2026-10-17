"""per-bot scratchpads (one row per bot, regardless of thread)

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "bot_scratchpads",
        sa.Column("actor_id", sa.String(36), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["actors.id"], ondelete="CASCADE"),
    )


def downgrade():
    op.drop_table("bot_scratchpads")
