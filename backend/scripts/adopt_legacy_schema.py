"""Adopt a pre-Alembic database so `alembic upgrade head` can run on it.

Before issue #149 the app created its tables with
``Base.metadata.create_all`` on every startup. Those databases have the full
schema but **no** ``alembic_version`` row, so a plain ``alembic upgrade head``
would try to replay ``001_initial`` against tables that already exist and
fail.

This script detects that state and stamps the database at ``head`` instead,
which records the migration history without re-running it. The stamp is safe
because ``create_all`` builds the schema from the current models — the same
shape ``head`` produces.

It is a no-op on:
  * a brand-new empty database (Alembic will build it from scratch), and
  * any database already under Alembic control.

Run before ``alembic upgrade head``; see ``entrypoint.sh``.
"""

from __future__ import annotations

import logging
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("adopt_legacy_schema")

# Present in every schema this app has ever created; its presence means the
# database was provisioned, one way or another.
SENTINEL_TABLE = "users"


def main() -> int:
    """Stamp a legacy create_all database at head. Returns a process exit code."""
    # Alembic's own engine is sync; strip the async driver from the URL.
    url = get_settings().DATABASE_URL.replace("+aiosqlite", "")
    engine = create_engine(url)

    try:
        table_names = set(inspect(engine).get_table_names())

        # The table alone isn't proof of adoption: a failed `upgrade` creates
        # alembic_version before erroring, leaving it empty. Only a recorded
        # revision means the database is genuinely under Alembic control.
        stamped = False
        if "alembic_version" in table_names:
            with engine.connect() as conn:
                stamped = conn.execute(text("SELECT 1 FROM alembic_version LIMIT 1")).first() is not None
    finally:
        engine.dispose()

    if stamped:
        logger.info("Database is already under Alembic control; nothing to adopt.")
        return 0

    if SENTINEL_TABLE not in table_names:
        logger.info("Empty database; Alembic will create the schema from scratch.")
        return 0

    logger.warning(
        "Found a pre-Alembic schema (tables present, no alembic_version). "
        "Stamping at head so migrations can proceed — see issue #149."
    )
    command.stamp(Config("alembic.ini"), "head")
    logger.info("Stamped at head.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
