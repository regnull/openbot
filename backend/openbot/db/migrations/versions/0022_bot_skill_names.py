"""bot skill_names: which skills a bot may load on demand

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = depends_on = None


def upgrade():
    op.add_column("bot_profiles", sa.Column("skill_names", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade():
    op.drop_column("bot_profiles", "skill_names")
