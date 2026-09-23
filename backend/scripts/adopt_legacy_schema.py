"""Adopt a pre-Alembic database so `alembic upgrade head` can run on it.

Before issue #149 the app created its tables with
``Base.metadata.create_all`` on every startup. Those databases have the full
schema but **no** ``alembic_version`` row, so a plain ``alembic upgrade head``
would try to replay ``001_initial`` against tables that already exist and
fail.

This script detects that state and stamps the database at ``head`` instead,
which records the migration history without re-running it. The stamp is only
safe because ``create_all`` builds the schema from the current models — the
same shape ``head`` produces — so before stamping we verify that shape: every
table and column the models declare must actually exist in the database
(issue #168). That catches old-shape or partially-migrated databases — e.g.
one missing ``app_settings`` or ``podcasts.unplayed_episodes`` — which must
not be marked fully migrated. On a mismatch the script exits non-zero so the
container entrypoint fails loudly instead of booting against a broken schema.

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
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.models import Base

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("adopt_legacy_schema")

# Present in every schema this app has ever created; its presence means the
# database was provisioned, one way or another.
SENTINEL_TABLE = "users"


def schema_gaps(engine: Engine) -> list[str]:
    """Tables and columns the current models expect but the database lacks.

    A genuine ``create_all`` database was built from the current models, so it
    contains every one of these. Anything missing means the database predates
    head (old-shape or partially migrated) and must not be stamped.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    gaps: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            gaps.append(f"table {table.name!r}")
            continue
        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
        gaps.extend(
            f"column {table.name}.{column.name}" for column in table.columns if column.name not in existing_columns
        )
    return gaps


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

        if stamped:
            logger.info("Database is already under Alembic control; nothing to adopt.")
            return 0

        if SENTINEL_TABLE not in table_names:
            logger.info("Empty database; Alembic will create the schema from scratch.")
            return 0

        # Tables exist but there's no migration history. Stamping at head is
        # only correct if the schema really is the shape head produces.
        gaps = schema_gaps(engine)
    finally:
        engine.dispose()

    if gaps:
        logger.error(
            "Refusing to adopt this database: it is not empty, not under "
            "Alembic control, and does not match the schema that "
            "`alembic upgrade head` produces. Missing: %s. It looks like an "
            "old-shape or partially-migrated database — stamping it at head "
            "would permanently mark all migrations as applied without running "
            "them. Determine which revision the schema actually corresponds "
            "to and run `alembic stamp <revision>` manually (or restore from "
            "a backup), then start the app again.",
            ", ".join(gaps),
        )
        return 1

    logger.warning(
        "Found a pre-Alembic schema (tables present, no alembic_version). "
        "Schema matches the current models; stamping at head so migrations "
        "can proceed — see issue #149."
    )
    command.stamp(Config("alembic.ini"), "head")
    logger.info("Stamped at head.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
