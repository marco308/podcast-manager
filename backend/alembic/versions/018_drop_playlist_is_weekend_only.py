"""Drop playlists.is_weekend_only (issue #238)

Revision ID: 018_drop_playlist_is_weekend_only
Revises: 016_playlist_spotify_link_unique
Create Date: 2026-09-22

The setting only froze a playlist Monday to Thursday. Every rebuild is a full
replace from unplayed state, so Friday's playlist came out the same either
way; the only visible effect was holding back midweek releases and refusing
a manual Run. Removed rather than renamed.

Revises 016_playlist_spotify_link_unique, the current head — see "Migration
chain" in CLAUDE.md for why that file's number is out of order.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018_drop_playlist_is_weekend_only"
down_revision: str | None = "016_playlist_spotify_link_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.drop_column("is_weekend_only")


def downgrade() -> None:
    # The flag's values are gone; every playlist comes back as a normal one.
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.add_column(
            sa.Column("is_weekend_only", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
