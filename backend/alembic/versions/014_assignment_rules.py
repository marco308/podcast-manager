"""Per-assignment episode rules (issue #249)

Revision ID: 014_assignment_rules
Revises: 013_reconcile_schema_drift
Create Date: 2026-09-22

Moves "what a show contributes" from the playlist (``episode_mode``) and the
podcast (``is_sequential`` as the only direction control) onto the assignment
row, with playlist-level defaults. ``ordering_mode`` is split into
``arrangement`` + ``date_direction``. See docs/design/assignment-rules.md.

Backfill:

    episode_mode      -> default_episode_limit   (latest_only=1, all_unplayed=0)
    ordering_mode     -> arrangement, date_direction
        DEFAULT             by_date, newest_first if latest_only else oldest_first
        CHRONOLOGICAL_ASC   by_date, oldest_first
        CHRONOLOGICAL_DESC  by_date, newest_first
        PODCAST_ORDER       by_position
    (all)             -> default_pick_from = newest; assignment overrides NULL

Sequential shows keep oldest-first through the ``is_sequential`` hint, so no
per-assignment override needs writing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014_assignment_rules"
down_revision: str | None = "013_reconcile_schema_drift"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- playlists: add the new columns with the model defaults ------------
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.add_column(
            sa.Column("default_episode_limit", sa.Integer(), nullable=False, server_default="0"),
        )
        batch_op.add_column(
            sa.Column("default_pick_from", sa.String(length=10), nullable=False, server_default="newest"),
        )
        batch_op.add_column(
            sa.Column("arrangement", sa.String(length=20), nullable=False, server_default="by_position"),
        )
        batch_op.add_column(
            sa.Column("date_direction", sa.String(length=20), nullable=False, server_default="oldest_first"),
        )

    # --- backfill from the old columns --------------------------------------
    op.execute("UPDATE playlists SET default_episode_limit = 1 WHERE episode_mode = 'latest_only'")
    op.execute("UPDATE playlists SET default_episode_limit = 0 WHERE episode_mode <> 'latest_only'")

    # ordering_mode was a non-native Enum storing the member *names*.
    op.execute("UPDATE playlists SET arrangement = 'by_position' WHERE ordering_mode = 'PODCAST_ORDER'")
    op.execute("UPDATE playlists SET arrangement = 'by_date' WHERE ordering_mode <> 'PODCAST_ORDER'")
    op.execute("UPDATE playlists SET date_direction = 'oldest_first' WHERE ordering_mode = 'CHRONOLOGICAL_ASC'")
    op.execute("UPDATE playlists SET date_direction = 'newest_first' WHERE ordering_mode = 'CHRONOLOGICAL_DESC'")
    op.execute(
        "UPDATE playlists SET date_direction = CASE WHEN episode_mode = 'latest_only' "
        "THEN 'newest_first' ELSE 'oldest_first' END WHERE ordering_mode = 'DEFAULT'"
    )

    # --- drop the old columns and clear the server defaults -----------------
    # (the model supplies Python-side defaults; server defaults were only
    # needed to add NOT NULL columns to a populated table)
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.drop_column("episode_mode")
        batch_op.drop_column("ordering_mode")
        batch_op.alter_column("default_episode_limit", server_default=None)
        batch_op.alter_column("default_pick_from", server_default=None)
        batch_op.alter_column("arrangement", server_default=None)
        batch_op.alter_column("date_direction", server_default=None)

    # --- playlist_podcasts: nullable overrides --------------------------------
    with op.batch_alter_table("playlist_podcasts") as batch_op:
        batch_op.add_column(sa.Column("episode_limit", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pick_from", sa.String(length=10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("playlist_podcasts") as batch_op:
        batch_op.drop_column("pick_from")
        batch_op.drop_column("episode_limit")

    with op.batch_alter_table("playlists") as batch_op:
        batch_op.add_column(
            sa.Column("episode_mode", sa.String(length=20), nullable=False, server_default="all_unplayed"),
        )
        batch_op.add_column(
            sa.Column(
                "ordering_mode",
                sa.Enum(
                    "DEFAULT",
                    "PODCAST_ORDER",
                    "CHRONOLOGICAL_ASC",
                    "CHRONOLOGICAL_DESC",
                    name="playlistorderingmode",
                    native_enum=False,
                ),
                nullable=False,
                server_default="DEFAULT",
            ),
        )

    # Reverse mapping. Per-assignment overrides are lost; that is the
    # information the old model could not hold.
    op.execute("UPDATE playlists SET episode_mode = 'latest_only' WHERE default_episode_limit = 1")
    op.execute("UPDATE playlists SET ordering_mode = 'PODCAST_ORDER' WHERE arrangement = 'by_position'")
    op.execute(
        "UPDATE playlists SET ordering_mode = 'CHRONOLOGICAL_ASC' "
        "WHERE arrangement = 'by_date' AND date_direction = 'oldest_first'"
    )
    op.execute(
        "UPDATE playlists SET ordering_mode = 'CHRONOLOGICAL_DESC' "
        "WHERE arrangement = 'by_date' AND date_direction = 'newest_first'"
    )

    with op.batch_alter_table("playlists") as batch_op:
        batch_op.drop_column("date_direction")
        batch_op.drop_column("arrangement")
        batch_op.drop_column("default_pick_from")
        batch_op.drop_column("default_episode_limit")
