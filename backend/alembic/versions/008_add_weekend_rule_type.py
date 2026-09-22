"""Add weekend to playlist rule type enum

Revision ID: 008_add_weekend_rule_type
Revises: 007_multi_category
Create Date: 2026-02-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '008_add_weekend_rule_type'
down_revision: Union[str, None] = '007_multi_category'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite doesn't enforce enum constraints at the column level when using
    # VARCHAR, so no schema change is needed. The new enum value is handled
    # by the application layer (SQLAlchemy + Pydantic validation).
    pass


def downgrade() -> None:
    # Remove any playlists with weekend rule type
    op.execute("DELETE FROM playlists WHERE rule_type = 'weekend'")
