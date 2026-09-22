"""Track how long a podcast has been gone from the Spotify library (issue #155)

Revision ID: 016_podcast_missing_since
Revises: 015_unplayed_episodes_nullable
Create Date: 2026-09-22

``POST /podcasts/sync`` deletes podcasts that have left the library, which
cascades to their playlist assignments. One paginated walk of ``GET /me/shows``
is not a guaranteed snapshot, so a show missing from a walk is marked here
first and only deleted once it has stayed missing for the grace period
(``UNSUBSCRIBE_GRACE`` in ``routers/podcasts.py``). NULL = present.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016_podcast_missing_since"
down_revision: str | None = "015_unplayed_episodes_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("podcasts", sa.Column("missing_since", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("podcasts", "missing_since")
