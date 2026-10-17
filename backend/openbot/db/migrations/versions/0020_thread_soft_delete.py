"""soft-delete threads: deleted_at instead of removing the rows

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = depends_on = None


def upgrade():
    op.add_column("threads", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("threads", "deleted_at")
