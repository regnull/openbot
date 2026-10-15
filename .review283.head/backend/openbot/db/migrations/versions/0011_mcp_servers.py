"""remote MCP servers added from the Settings UI

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-17 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "mcp_servers",
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("mcp_servers")
