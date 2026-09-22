"""Initial migration - create all tables

Revision ID: 001_initial
Revises: 
Create Date: 2024-12-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('spotify_id', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('access_token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text(), nullable=False),
        sa.Column('token_expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_spotify_id', 'users', ['spotify_id'], unique=True)

    # Create podcasts table
    op.create_table(
        'podcasts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('spotify_id', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('publisher', sa.String(length=255), nullable=True),
        sa.Column('total_episodes', sa.Integer(), nullable=True, default=0),
        sa.Column('category', sa.Enum('primary', 'news', 'background', 'none', name='podcastcategory'), nullable=False, default='none'),
        sa.Column('is_sequential', sa.Boolean(), nullable=False, default=False),
        sa.Column('is_weekend_only', sa.Boolean(), nullable=False, default=False),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_podcasts_spotify_id', 'podcasts', ['spotify_id'], unique=True)
    op.create_index('ix_podcasts_category', 'podcasts', ['category'], unique=False)

    # Create playlists table
    op.create_table(
        'playlists',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('spotify_playlist_id', sa.String(length=255), nullable=True),
        sa.Column('rule_type', sa.Enum('primary', 'news', 'morning', 'background', name='playlistruletype'), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('last_updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create sync_logs table
    op.create_table(
        'sync_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.Enum('pending', 'running', 'success', 'failed', name='syncstatus'), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('sync_logs')
    op.drop_table('playlists')
    op.drop_index('ix_podcasts_category', table_name='podcasts')
    op.drop_index('ix_podcasts_spotify_id', table_name='podcasts')
    op.drop_table('podcasts')
    op.drop_index('ix_users_spotify_id', table_name='users')
    op.drop_table('users')
