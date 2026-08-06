"""Reconcile drift between the models and the migration chain

Revision ID: 013_reconcile_schema_drift
Revises: 012_add_sync_log_failure_classification
Create Date: 2026-08-06

Migration ``005_add_unplayed_episodes`` is an empty placeholder — its file was
lost and it was recreated as a no-op on the assumption that the column already
existed in the live database. That was true there, but it means the chain
never actually creates ``podcasts.unplayed_episodes``. Until now the gap was
masked by ``Base.metadata.create_all`` running on every startup and quietly
adding the missing column.

Issue #149 made Alembic the single owner of the schema and removed that
startup call, which turns the gap into a hard failure: a freshly-migrated
database has no ``podcasts.unplayed_episodes`` and every podcast query dies
with ``no such column``.

This migration brings the chain back in line with the models:

1. ``podcasts.unplayed_episodes`` — add it (the real fix).
2. ``ix_app_settings_key`` — recreate as UNIQUE. The model declares
   ``unique=True`` and the settings upsert in ``reschedule_playlist_update``
   relies on one row per key, but ``011`` created a non-unique index.
3. ``podcasts.total_episodes`` — tighten to NOT NULL to match the model.

Every step is guarded so this is safe to run against databases that already
have the target state — the live database, and any ``create_all``-provisioned
one adopted via ``scripts/adopt_legacy_schema.py``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013_reconcile_schema_drift"
down_revision: str | None = "012_add_sync_log_failure_classification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _podcast_columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("podcasts")}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # 1. The column migration 005 never created.
    if "unplayed_episodes" not in _podcast_columns():
        op.add_column(
            "podcasts",
            sa.Column("unplayed_episodes", sa.Integer(), nullable=False, server_default="0"),
        )

    # 2. app_settings.key must be unique — the schedule upsert depends on it.
    app_settings_indexes = {ix["name"]: ix for ix in inspector.get_indexes("app_settings")}
    existing = app_settings_indexes.get("ix_app_settings_key")
    if existing is not None and not existing.get("unique"):
        op.drop_index("ix_app_settings_key", table_name="app_settings")
        op.create_index("ix_app_settings_key", "app_settings", ["key"], unique=True)
    elif existing is None:
        op.create_index("ix_app_settings_key", "app_settings", ["key"], unique=True)

    # 3. total_episodes is non-optional in the model. Backfill before tightening
    #    so an existing NULL can't fail the constraint.
    total_episodes = next((c for c in inspector.get_columns("podcasts") if c["name"] == "total_episodes"), None)
    if total_episodes is not None and total_episodes.get("nullable", True):
        op.execute("UPDATE podcasts SET total_episodes = 0 WHERE total_episodes IS NULL")
        with op.batch_alter_table("podcasts") as batch_op:
            batch_op.alter_column(
                "total_episodes",
                existing_type=sa.Integer(),
                nullable=False,
                existing_server_default=None,
            )


def downgrade() -> None:
    with op.batch_alter_table("podcasts") as batch_op:
        batch_op.alter_column("total_episodes", existing_type=sa.Integer(), nullable=True)

    op.drop_index("ix_app_settings_key", table_name="app_settings")
    op.create_index("ix_app_settings_key", "app_settings", ["key"], unique=False)

    if "unplayed_episodes" in _podcast_columns():
        op.drop_column("podcasts", "unplayed_episodes")
