"""Add index on playlist_podcasts.podcast_id

Revision ID: 010_add_podcast_id_index
Revises: 009_playlist_podcast_assignments
Create Date: 2026-03-14

"""
from typing import Sequence, Union
from alembic import op

revision: str = '010_add_podcast_id_index'
down_revision: Union[str, None] = '009_playlist_podcast_assignments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_playlist_podcasts_podcast_id', 'playlist_podcasts', ['podcast_id'])


def downgrade() -> None:
    op.drop_index('ix_playlist_podcasts_podcast_id', table_name='playlist_podcasts')
