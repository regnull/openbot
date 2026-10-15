"""encrypted OAuth credentials for remote MCP servers

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-17 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "mcp_credentials",
        sa.Column("server", sa.String(length=64), primary_key=True),
        sa.Column("client_info", sa.Text(), nullable=True),
        sa.Column("tokens", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("mcp_credentials")
