"""add thread working directory

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("threads", sa.Column("working_directory", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("threads", "working_directory")
