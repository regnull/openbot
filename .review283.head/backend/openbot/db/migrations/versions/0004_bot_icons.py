"""add bot icons

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from openbot.bot_icons import DEFAULT_BOT_ICON

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("bot_profiles", sa.Column("icon", sa.String(length=32), nullable=False,
                                             server_default=DEFAULT_BOT_ICON))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("bot_profiles", "icon")
