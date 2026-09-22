"""Add podcasts.unfollowed_at (issue #240)

Revision ID: 016_podcast_unfollowed_at
Revises: 015_podcast_is_archived
Create Date: 2026-09-22

The library sync now reconciles unfollows: a podcast that is no longer in
``GET /me/shows`` is stamped with ``unfollowed_at`` instead of being deleted,
so a Spotify page that goes missing for one run cannot destroy the show's
playlist assignments. A stamped podcast contributes no episodes to a build,
and the next sync that sees it again clears the stamp.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016_podcast_unfollowed_at"
down_revision: str | None = "015_podcast_is_archived"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("podcasts") as batch_op:
        batch_op.add_column(sa.Column("unfollowed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("podcasts") as batch_op:
        batch_op.drop_column("unfollowed_at")
