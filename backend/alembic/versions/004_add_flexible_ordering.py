"""Add flexible playlist ordering

Revision ID: 004_add_flexible_ordering
Revises: 003_add_user_id
Create Date: 2025-12-07

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_add_flexible_ordering'
down_revision: Union[str, None] = '003_add_user_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add ordering_mode to playlists table
    op.add_column('playlists', sa.Column(
        'ordering_mode',
        sa.Enum('DEFAULT', 'PODCAST_ORDER', 'CHRONOLOGICAL_ASC', 'CHRONOLOGICAL_DESC',
                name='playlistorderingmode', native_enum=False),
        nullable=False,
        server_default='DEFAULT'
    ))

    # Add playlist_order to podcasts table
    op.add_column('podcasts', sa.Column(
        'playlist_order',
        sa.Integer(),
        nullable=True
    ))
    op.create_index('ix_podcasts_playlist_order', 'podcasts', ['playlist_order'])

    # Data migration: Copy morning_order to playlist_order for NEWS category podcasts
    op.execute("""
        UPDATE podcasts
        SET playlist_order = morning_order
        WHERE category = 'news' AND morning_order IS NOT NULL
    """)

    # Set existing MORNING playlists to use PODCAST_ORDER mode
    op.execute("""
        UPDATE playlists
        SET ordering_mode = 'PODCAST_ORDER'
        WHERE rule_type = 'morning'
    """)


def downgrade() -> None:
    # Remove index
    op.drop_index('ix_podcasts_playlist_order', 'podcasts')

    # Remove playlist_order column
    op.drop_column('podcasts', 'playlist_order')

    # Remove ordering_mode column
    op.drop_column('playlists', 'ordering_mode')
