"""Add user_id to playlists table

Revision ID: 003_add_user_id
Revises: 002_add_morning_order
Create Date: 2025-12-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_add_user_id'
down_revision: Union[str, None] = '002_add_morning_order'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite doesn't support ALTER COLUMN, so we need to recreate the table
    # with batch_alter_table for SQLite compatibility
    with op.batch_alter_table('playlists', schema=None) as batch_op:
        # Add user_id column as non-nullable with default value 1
        batch_op.add_column(
            sa.Column('user_id', sa.Integer(), nullable=False, server_default='1')
        )
        # Add foreign key constraint
        batch_op.create_foreign_key(
            'fk_playlists_user_id',
            'users',
            ['user_id'], ['id'],
            ondelete='CASCADE'
        )


def downgrade() -> None:
    with op.batch_alter_table('playlists', schema=None) as batch_op:
        batch_op.drop_constraint('fk_playlists_user_id', type_='foreignkey')
        batch_op.drop_column('user_id')
