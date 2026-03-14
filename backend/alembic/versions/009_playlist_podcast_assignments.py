"""Replace categories with direct playlist-podcast assignments

Revision ID: 009_playlist_podcast_assignments
Revises: 008_add_weekend_rule_type
Create Date: 2026-03-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '009_playlist_podcast_assignments'
down_revision: Union[str, None] = '008_add_weekend_rule_type'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create playlist_podcasts join table
    op.create_table(
        'playlist_podcasts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('playlist_id', sa.Integer(), sa.ForeignKey('playlists.id', ondelete='CASCADE'), nullable=False),
        sa.Column('podcast_id', sa.Integer(), sa.ForeignKey('podcasts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('playlist_id', 'podcast_id', name='uq_playlist_podcast'),
    )

    # 2. Add episode_mode column to playlists (default 'all_unplayed')
    op.add_column('playlists', sa.Column(
        'episode_mode',
        sa.String(20),
        nullable=False,
        server_default='all_unplayed',
    ))

    # 3. Add is_weekend_only column to playlists (default False)
    op.add_column('playlists', sa.Column(
        'is_weekend_only',
        sa.Boolean(),
        nullable=False,
        server_default=sa.text('0'),
    ))

    # 4. Migrate data: for each playlist, based on its rule_type, find podcasts
    # with matching category and insert into playlist_podcasts.
    # rule_type is stored as lowercase in SQLite (e.g., 'primary', 'news').
    # Categories are stored as JSON arrays with lowercase values (e.g., '["primary"]').

    # primary playlists -> podcasts with "primary" category
    op.execute("""
        INSERT INTO playlist_podcasts (playlist_id, podcast_id, position)
        SELECT p.id, pc.id, pc.playlist_order
        FROM playlists p
        CROSS JOIN podcasts pc
        WHERE LOWER(p.rule_type) = 'primary'
        AND pc.categories LIKE '%"primary"%'
    """)

    # news playlists -> podcasts with "news" category
    op.execute("""
        INSERT INTO playlist_podcasts (playlist_id, podcast_id, position)
        SELECT p.id, pc.id, pc.playlist_order
        FROM playlists p
        CROSS JOIN podcasts pc
        WHERE LOWER(p.rule_type) = 'news'
        AND pc.categories LIKE '%"news"%'
    """)

    # morning playlists -> podcasts with "news" category (morning reused news)
    op.execute("""
        INSERT INTO playlist_podcasts (playlist_id, podcast_id, position)
        SELECT p.id, pc.id, pc.playlist_order
        FROM playlists p
        CROSS JOIN podcasts pc
        WHERE LOWER(p.rule_type) = 'morning'
        AND pc.categories LIKE '%"news"%'
    """)

    # background playlists -> podcasts with "background" category
    op.execute("""
        INSERT INTO playlist_podcasts (playlist_id, podcast_id, position)
        SELECT p.id, pc.id, pc.playlist_order
        FROM playlists p
        CROSS JOIN podcasts pc
        WHERE LOWER(p.rule_type) = 'background'
        AND pc.categories LIKE '%"background"%'
    """)

    # weekend playlists -> podcasts with "weekend" category
    op.execute("""
        INSERT INTO playlist_podcasts (playlist_id, podcast_id, position)
        SELECT p.id, pc.id, pc.playlist_order
        FROM playlists p
        CROSS JOIN podcasts pc
        WHERE LOWER(p.rule_type) = 'weekend'
        AND pc.categories LIKE '%"weekend"%'
    """)

    # 5. Set episode_mode based on rule_type
    # news and morning -> 'latest_only'
    op.execute("""
        UPDATE playlists
        SET episode_mode = 'latest_only'
        WHERE LOWER(rule_type) IN ('news', 'morning')
    """)
    # primary, background, weekend -> 'all_unplayed' (already default)

    # 6. Set is_weekend_only=True for weekend playlists
    op.execute("""
        UPDATE playlists
        SET is_weekend_only = 1
        WHERE LOWER(rule_type) = 'weekend'
    """)

    # 7. Drop rule_type from playlists, and drop category-related columns from podcasts
    with op.batch_alter_table('playlists') as batch_op:
        batch_op.drop_column('rule_type')

    with op.batch_alter_table('podcasts') as batch_op:
        batch_op.drop_index('ix_podcasts_playlist_order')
        batch_op.drop_index('ix_podcasts_morning_order')
        batch_op.drop_column('categories')
        batch_op.drop_column('is_weekend_only')
        batch_op.drop_column('morning_order')
        batch_op.drop_column('playlist_order')


def downgrade() -> None:
    # 1. Re-add columns to podcasts
    with op.batch_alter_table('podcasts') as batch_op:
        batch_op.add_column(sa.Column(
            'categories',
            sa.JSON(),
            nullable=False,
            server_default='[]',
        ))
        batch_op.add_column(sa.Column(
            'is_weekend_only',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('0'),
        ))
        batch_op.add_column(sa.Column(
            'morning_order',
            sa.Integer(),
            nullable=True,
        ))
        batch_op.add_column(sa.Column(
            'playlist_order',
            sa.Integer(),
            nullable=True,
        ))

    op.create_index('ix_podcasts_morning_order', 'podcasts', ['morning_order'])
    op.create_index('ix_podcasts_playlist_order', 'podcasts', ['playlist_order'])

    # 2. Re-add rule_type to playlists
    with op.batch_alter_table('playlists') as batch_op:
        batch_op.add_column(sa.Column(
            'rule_type',
            sa.String(20),
            nullable=False,
            server_default='primary',
        ))

    # 3. Migrate data back: infer rule_type from episode_mode + is_weekend_only
    # weekend playlists
    op.execute("""
        UPDATE playlists
        SET rule_type = 'weekend'
        WHERE is_weekend_only = 1
    """)
    # latest_only -> news (approximation, loses morning distinction)
    op.execute("""
        UPDATE playlists
        SET rule_type = 'news'
        WHERE episode_mode = 'latest_only' AND is_weekend_only = 0
    """)
    # all_unplayed + not weekend -> could be primary or background, default to primary
    op.execute("""
        UPDATE playlists
        SET rule_type = 'primary'
        WHERE episode_mode = 'all_unplayed' AND is_weekend_only = 0
    """)

    # 4. Migrate podcast categories back from join table
    # For each podcast, collect categories from the playlists it's assigned to
    # We use rule_type which we just restored
    # GROUP_CONCAT produces 'primary,news' — we need '["primary","news"]',
    # so use REPLACE to convert ',' to '","' and wrap with '["..."]'.
    op.execute("""
        UPDATE podcasts
        SET categories = COALESCE(
            (SELECT '["' || REPLACE(GROUP_CONCAT(DISTINCT
                CASE LOWER(p.rule_type)
                    WHEN 'morning' THEN 'news'
                    ELSE LOWER(p.rule_type)
                END
            ), ',', '","') || '"]'
            FROM playlist_podcasts pp
            JOIN playlists p ON p.id = pp.playlist_id
            WHERE pp.podcast_id = podcasts.id),
            '[]'
        )
    """)

    # Restore playlist_order from join table position (take max position across playlists)
    op.execute("""
        UPDATE podcasts
        SET playlist_order = (
            SELECT pp.position
            FROM playlist_podcasts pp
            WHERE pp.podcast_id = podcasts.id
            AND pp.position IS NOT NULL
            ORDER BY pp.position
            LIMIT 1
        )
    """)

    # 5. Drop new columns from playlists
    with op.batch_alter_table('playlists') as batch_op:
        batch_op.drop_column('episode_mode')
        batch_op.drop_column('is_weekend_only')

    # 6. Drop playlist_podcasts table
    op.drop_table('playlist_podcasts')
