"""record token usage per run

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-16 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("prompt_tokens", "completion_tokens", "cache_read_tokens", "total_tokens", "model_calls")


def upgrade() -> None:
    """Upgrade schema."""
    for name in COLUMNS:
        op.add_column("runs", sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for name in reversed(COLUMNS):
        op.drop_column("runs", name)
