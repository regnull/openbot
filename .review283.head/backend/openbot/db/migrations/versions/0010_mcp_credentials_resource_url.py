"""bind MCP credentials to the server URL they were granted for

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-17 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("mcp_credentials", sa.Column("resource_url", sa.String(length=2000), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("mcp_credentials") as batch:
        batch.drop_column("resource_url")
