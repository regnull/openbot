"""mcp_servers holds every server spec (both transports, encrypted secrets)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-17 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("mcp_servers") as batch:
        batch.add_column(sa.Column("transport", sa.String(length=16), nullable=False, server_default="http"))
        batch.add_column(sa.Column("command", sa.String(length=2000), nullable=True))
        batch.add_column(sa.Column("args", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("cwd", sa.String(length=2000), nullable=True))
        batch.add_column(sa.Column("secrets", sa.Text(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        batch.alter_column("url", existing_type=sa.String(length=2000), nullable=True)
        # Rows so far were UI-added remote servers with no headers; nothing to carry over.
        batch.drop_column("headers")


def downgrade() -> None:
    """Downgrade schema."""
    # Revision 0011 only knows remote servers with a URL; local (stdio) rows cannot be represented
    # there, so they go rather than failing the NOT NULL re-imposition mid-batch.
    op.execute("DELETE FROM mcp_servers WHERE url IS NULL")
    with op.batch_alter_table("mcp_servers") as batch:
        batch.add_column(sa.Column("headers", sa.JSON(), nullable=True))
        batch.alter_column("url", existing_type=sa.String(length=2000), nullable=False)
        for col in ("updated_at", "secrets", "cwd", "args", "command", "transport"):
            batch.drop_column(col)
