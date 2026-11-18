"""run snapshots: files changed during a run, its diff, and whether its window was shared

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = depends_on = None


def upgrade():
    op.add_column("runs", sa.Column("changed_files", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("diff", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("changes_shared", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("runs", "changes_shared")
    op.drop_column("runs", "diff")
    op.drop_column("runs", "changed_files")