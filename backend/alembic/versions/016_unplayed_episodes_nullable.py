"""Make podcasts.unplayed_episodes nullable ("not counted yet") (issue #155)

Revision ID: 016_unplayed_episodes_nullable
Revises: 015_podcast_is_archived
Create Date: 2026-09-22

``unplayed_episodes`` used to be written by ``POST /podcasts/sync``, which
extrapolated it from the newest 50 episodes and so overstated it. The sync no
longer touches it; the playlist build records the exact count when it has read
a show's whole catalogue. A show that hasn't been counted that way has no
honest value, so the column becomes nullable and NULL means "not counted".

Existing values can't be told apart (extrapolated vs. counted), so they are all
cleared. The next build refills every show it reads in full.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016_unplayed_episodes_nullable"
down_revision: str | None = "015_podcast_is_archived"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("podcasts") as batch_op:
        batch_op.alter_column(
            "unplayed_episodes",
            existing_type=sa.Integer(),
            nullable=True,
            server_default=None,
        )
    op.execute("UPDATE podcasts SET unplayed_episodes = NULL")


def downgrade() -> None:
    op.execute("UPDATE podcasts SET unplayed_episodes = 0 WHERE unplayed_episodes IS NULL")
    with op.batch_alter_table("podcasts") as batch_op:
        batch_op.alter_column(
            "unplayed_episodes",
            existing_type=sa.Integer(),
            nullable=False,
            server_default="0",
        )
