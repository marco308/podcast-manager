"""Fail when the migrated schema drifts from the SQLAlchemy models.

Run against a database that is already at ``alembic upgrade head`` (CI does
exactly that on a scratch SQLite file). Uses Alembic's autogenerate
comparison: any reported difference means a model changed without a matching
migration — the drift class that produced issue #149's missing
``podcasts.unplayed_episodes`` column.

Exit code 0 when the chain and the models agree, 1 when they differ.
"""

from __future__ import annotations

import logging
import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import app.models  # noqa: F401  — registers every model on Base.metadata
from app.config import get_settings
from app.database import Base

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("check_migration_drift")


def main() -> int:
    """Compare Base.metadata against the migrated database. Returns an exit code."""
    # Alembic's comparison runs on a sync engine; strip the async driver.
    url = get_settings().DATABASE_URL.replace("+aiosqlite", "")
    engine = create_engine(url)

    try:
        with engine.connect() as conn:
            diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()

    if diffs:
        logger.error("Schema drift between the models and the migrated database:")
        for diff in diffs:
            logger.error("  %s", diff)
        logger.error(
            "The migration chain does not produce the schema the models "
            "declare. Add a migration for the model change (or fix the "
            "migration) — do not rely on create_all (issue #149)."
        )
        return 1

    logger.info("No drift: the migration chain and the models agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
