"""Store session IDs as SHA-256 hashes

Revision ID: 020_hash_session_ids
Revises: 019_podcast_unplayed_counted_at
Create Date: 2026-09-23

``sessions.session_id`` held the bearer credential itself, so anyone with a
copy of the database (a backup, a stray ``podcast_manager.db``) could sign in
as the user. The app now stores the hex SHA-256 of the ID and hashes the
cookie on every lookup (``services/session.py::hash_session_id``).

Existing rows are hashed in place, so signed-in browsers and the iOS app keep
their sessions. The column keeps its name and size (a hex SHA-256 is 64
characters, the same as the column): an older image rolled back onto this
schema then just fails to find any session and asks for a new sign-in,
rather than failing on a missing column.

``csrf_token`` stays as is: it's compared server-side against the stored
value and grants nothing without the session cookie.

Downgrade can't recover plaintext IDs from hashes, so it deletes every
session; everyone signs in again.
"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "020_hash_session_ids"
down_revision: str | None = "019_podcast_unplayed_counted_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _hash(session_id: str) -> str:
    # Same function as app.services.session.hash_session_id, copied so the
    # migration keeps working whatever later happens to the app code.
    return hashlib.sha256(session_id.encode()).hexdigest()


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, session_id FROM sessions")).fetchall()
    for row_id, session_id in rows:
        conn.execute(
            sa.text("UPDATE sessions SET session_id = :hashed WHERE id = :id"),
            {"hashed": _hash(session_id), "id": row_id},
        )


def downgrade() -> None:
    op.execute("DELETE FROM sessions")
