"""Add podcasts.is_archived (issue #247)

Revision ID: 015_podcast_is_archived
Revises: 014_assignment_rules
Create Date: 2026-09-22

An archived podcast is hidden from the app — podcast lists, dashboard counts
and the assignment selects — but stays followed on Spotify. Unfollowing
remains the separate, destructive action.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015_podcast_is_archived"
down_revision: str | None = "014_assignment_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("podcasts") as batch_op:
        batch_op.add_column(
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    with op.batch_alter_table("podcasts") as batch_op:
        batch_op.drop_column("is_archived")
