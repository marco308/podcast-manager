"""Unique (user_id, spotify_playlist_id) on playlists (issue #245)

Revision ID: 016_playlist_spotify_link_unique
Revises: 017_podcast_missing_since
Create Date: 2026-09-22

Relinked after 017 (issue #240). This migration and 016/017 were written off
the same parent (015) on separate branches and merged independently, which
left the chain with two heads and ``alembic upgrade head`` failing outright —
including in the Docker entrypoint. The revision id is deliberately left as
``016_...`` even though it now revises 017: renaming it would orphan any
database already stamped at it. The file name keeps the id, so the numbering
here records when it was written, not its place in the chain.

Two managed playlists pointing at one Spotify playlist overwrite each other on
every rebuild. The API refuses to create that, but a check-then-insert can be
raced; the constraint is what actually guarantees it. NULL stays free to
repeat — every playlist that has no link yet is NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016_playlist_spotify_link_unique"
down_revision: str | None = "017_podcast_missing_since"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "uq_playlists_user_spotify_playlist"


def upgrade() -> None:
    # Pre-existing duplicates can only have come from the old free-text field.
    # Clearing one automatically would decide which playlist keeps the link —
    # a data decision that belongs to the user, so fail with instructions.
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT user_id, spotify_playlist_id, COUNT(*) AS n FROM playlists "
                "WHERE spotify_playlist_id IS NOT NULL "
                "GROUP BY user_id, spotify_playlist_id HAVING n > 1"
            )
        )
        .fetchall()
    )
    if duplicates:
        clashes = ", ".join(str(row.spotify_playlist_id) for row in duplicates)
        raise RuntimeError(
            "Cannot add the unique Spotify link constraint: these Spotify playlist IDs are "
            f"linked to more than one managed playlist ({clashes}). They overwrite each other "
            "on every rebuild — clear the link on all but one playlist, then run the migration again."
        )

    with op.batch_alter_table("playlists") as batch_op:
        batch_op.create_unique_constraint(CONSTRAINT_NAME, ["user_id", "spotify_playlist_id"])


def downgrade() -> None:
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="unique")
