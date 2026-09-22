"""Record when podcasts.unplayed_episodes was counted (issue #241)

Revision ID: 019_podcast_unplayed_counted_at
Revises: 018_drop_playlist_is_weekend_only
Create Date: 2026-09-22

``unplayed_episodes`` is a by-product of a playlist build that read a show's
whole catalogue. Limited rules (latest only, next unfinished) do short reads
and never refresh it, so a count can sit unchanged for weeks while looking
current. ``unplayed_counted_at`` is written alongside it so both UIs can show
how old the number is.

Existing counts have no date, so they are cleared: a number whose age can't be
shown is the thing this migration exists to stop. The next build that reads a
show in full counts it again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019_podcast_unplayed_counted_at"
down_revision: str | None = "018_drop_playlist_is_weekend_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("podcasts", sa.Column("unplayed_counted_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE podcasts SET unplayed_episodes = NULL")


def downgrade() -> None:
    op.drop_column("podcasts", "unplayed_counted_at")
