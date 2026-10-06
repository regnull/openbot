"""allow bots to load repository instructions

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = depends_on = None
def upgrade():
    op.add_column("bot_profiles", sa.Column("load_repository_instructions", sa.Boolean(), nullable=False, server_default=sa.false()))
def downgrade():
    op.drop_column("bot_profiles", "load_repository_instructions")
