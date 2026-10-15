"""threads get a kind: chat (default) or direct

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-16 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # "direct" threads are the one-shot containers behind a post made straight into a bot's inbox;
    # they keep the every-item-has-a-thread invariant but stay out of the conversation views.
    op.add_column("threads", sa.Column("kind", sa.String(length=16), nullable=False, server_default="chat"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("threads") as batch:
        batch.drop_column("kind")
