"""every inbox item belongs to a thread

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-16 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Every code path already sets thread_id; a threadless item would be unreachable by the UI
    # and the workers, so any stragglers are junk rather than data.
    op.execute("DELETE FROM inbox_items WHERE thread_id IS NULL")
    with op.batch_alter_table("inbox_items") as batch:
        batch.alter_column("thread_id", existing_type=sa.String(length=36), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("inbox_items") as batch:
        batch.alter_column("thread_id", existing_type=sa.String(length=36), nullable=True)
