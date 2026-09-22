"""Convert single category column to multi-category JSON column

Revision ID: 007_multi_category
Revises: 006_add_sessions
Create Date: 2026-02-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '007_multi_category'
down_revision: Union[str, None] = '006_add_sessions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new categories JSON column
    op.add_column('podcasts', sa.Column(
        'categories',
        sa.JSON(),
        nullable=False,
        server_default='[]'
    ))

    # Migrate data: "none"/"NONE" -> [], others -> ["value"] (lowercase)
    op.execute("""
        UPDATE podcasts
        SET categories = CASE
            WHEN LOWER(category) = 'none' OR category IS NULL THEN '[]'
            ELSE '["' || LOWER(category) || '"]'
        END
    """)

    # Drop old category column and its index
    with op.batch_alter_table('podcasts') as batch_op:
        batch_op.drop_index('ix_podcasts_category')
        batch_op.drop_column('category')


def downgrade() -> None:
    # Re-add the category column
    with op.batch_alter_table('podcasts') as batch_op:
        batch_op.add_column(sa.Column(
            'category',
            sa.Enum('primary', 'news', 'background', 'none', name='podcastcategory'),
            nullable=False,
            server_default='none'
        ))

    # Migrate back: take first category or default to 'none'.
    # A single-element list has no comma, so INSTR(...) = 0 and the SUBSTR
    # branch becomes SUBSTR(x, 2, -2) — a negative length, which SQLite reads
    # backwards from the start and returns '[' rather than the category
    # (issue #176). Strip the brackets/quotes instead.
    op.execute("""
        UPDATE podcasts
        SET category = CASE
            WHEN categories = '[]' OR categories IS NULL THEN 'none'
            WHEN INSTR(categories, ',') = 0 THEN REPLACE(REPLACE(REPLACE(
                categories, '[', ''), ']', ''), '"', '')
            ELSE REPLACE(REPLACE(
                SUBSTR(categories, 2, INSTR(categories, ',') - 2),
                '"', ''), ']', '')
        END
    """)

    # Recreate index
    op.create_index('ix_podcasts_category', 'podcasts', ['category'])

    # Drop categories column
    with op.batch_alter_table('podcasts') as batch_op:
        batch_op.drop_column('categories')
