"""Add failure classification columns to sync_logs

Revision ID: 012_add_sync_log_failure_classification
Revises: 011_add_app_settings
Create Date: 2026-05-14

Adds four nullable columns to ``sync_logs`` so the daily playlist update
job can record (a) why it failed, and (b) how much work it actually
attempted. All nullable / default-None — rows written before this
migration stay valid (issue #89).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '012_add_sync_log_failure_classification'
down_revision: Union[str, None] = '011_add_app_settings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sync_logs') as batch_op:
        batch_op.add_column(sa.Column('failure_code', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('playlists_attempted', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('playlists_failed', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('api_calls_used', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sync_logs') as batch_op:
        batch_op.drop_column('api_calls_used')
        batch_op.drop_column('playlists_failed')
        batch_op.drop_column('playlists_attempted')
        batch_op.drop_column('failure_code')
