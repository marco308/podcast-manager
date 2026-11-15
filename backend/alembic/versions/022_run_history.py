"""Run history: each playlist's last result and a manual run's outcome (issues #246, #242)

Revision ID: 022_run_history
Revises: 021_sleep_playlists
Create Date: 2026-11-15

``playlists.last_run_status`` / ``last_run_error`` / ``last_run_at`` hold the
outcome of the most recent build of each playlist, written by the daily
rebuild and by manual runs alike, so the clients can show a failed or
partial ("written from incomplete data") build next to "Updated 3 hours ago"
instead of only in a toast. ``last_updated_at`` keeps its meaning: the last
time the Spotify playlist was actually written.

``sync_logs.outcome`` holds a manual run's client-facing result (message and
per-playlist outcomes) so ``GET /api/jobs/runs/{id}`` can report it once an
async run has finished. Every column is nullable: existing rows have no
history to fill in.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "022_run_history"
down_revision: str | None = "021_sleep_playlists"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("playlists", sa.Column("last_run_status", sa.String(length=20), nullable=True))
    op.add_column("playlists", sa.Column("last_run_error", sa.String(length=500), nullable=True))
    op.add_column("playlists", sa.Column("last_run_at", sa.DateTime(), nullable=True))
    op.add_column("sync_logs", sa.Column("outcome", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sync_logs") as batch_op:
        batch_op.drop_column("outcome")
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.drop_column("last_run_at")
        batch_op.drop_column("last_run_error")
        batch_op.drop_column("last_run_status")
