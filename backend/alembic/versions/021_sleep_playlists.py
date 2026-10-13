"""Sleep playlists: playlists.kind and the sleep_episodes ledger (issue #331)

Revision ID: 021_sleep_playlists
Revises: 020_hash_session_ids
Create Date: 2026-10-13

A sleep playlist plays episodes already heard. ``kind`` says which kind a
playlist is; every existing playlist is ``standard``. ``sleep_episodes``
records each episode a sleep build has served, because falling asleep to a
finished episode makes Spotify report it as partially played again
(docs/design/sleep-playlists.md).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "021_sleep_playlists"
down_revision: str | None = "020_hash_session_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "playlists",
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="standard"),
    )
    op.create_table(
        "sleep_episodes",
        sa.Column("episode_id", sa.String(length=64), primary_key=True),
        sa.Column("first_served_at", sa.DateTime(), nullable=False),
        sa.Column("last_served_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sleep_episodes")
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.drop_column("kind")
