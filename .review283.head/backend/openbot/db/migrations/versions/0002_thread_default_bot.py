"""add thread default bot

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite cannot ALTER in a foreign key constraint without rebuilding the table, and this
    # nullable pointer is validated by the application. Keep the column simple for portable upgrades.
    op.add_column("threads", sa.Column("default_bot_actor_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("threads", "default_bot_actor_id")
