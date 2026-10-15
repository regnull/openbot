"""Activity log: the database-side timeline of message delivery, inbox queueing, pickup and run status.

Revision ID: 0014
Revises: 0013
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("event", sa.String(length=48), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("item_id", sa.String(length=36), nullable=True),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
    )
    op.create_index("ix_activity_thread", "activity_log", ["thread_id", "id"])
    op.create_index("ix_activity_actor", "activity_log", ["actor_id", "id"])
    op.create_index("ix_activity_run", "activity_log", ["run_id", "id"])
    op.create_index("ix_activity_created", "activity_log", ["created_at"])


def downgrade() -> None:
    for name in ("ix_activity_created", "ix_activity_run", "ix_activity_actor", "ix_activity_thread"):
        op.drop_index(name, table_name="activity_log")
    op.drop_table("activity_log")
