"""Add unplayed_episodes column to podcasts

Revision ID: 005_add_unplayed_episodes
Revises: 004_add_flexible_ordering
Create Date: 2025-12-07

Note: This migration was previously applied but the file was lost.
This is a placeholder to maintain alembic history consistency.
The unplayed_episodes column already exists in the database.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_add_unplayed_episodes'
down_revision: Union[str, None] = '004_add_flexible_ordering'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Column already exists - this is a placeholder migration
    pass


def downgrade() -> None:
    op.drop_column('podcasts', 'unplayed_episodes')
