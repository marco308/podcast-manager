"""Database configuration and session management."""

import logging
from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Create async engine
# Note: connect_args timeout (seconds) sets sqlite3.connect(timeout=) which is the
# busy timeout for aiosqlite. The PRAGMA below also sets it (in ms) for consistency.
# hide_parameters keeps bound values (session-ID hashes, CSRF tokens, encrypted
# Spotify tokens) out of SQL echo and out of the messages of logged DB errors.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.SQL_ECHO,
    hide_parameters=True,
    future=True,
    connect_args={"timeout": 30},
)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode and busy timeout to prevent 'database is locked' errors."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session.

    Note: since FastAPI 0.106 this teardown (including the commit below) runs
    *after* the response has been sent, so a client acting immediately on a
    2xx could race the commit. Mutating handlers therefore commit explicitly
    before returning; the post-yield commit stays as a backstop for writes
    made in dependencies (e.g. session last-accessed updates on GETs).
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except HTTPException:
            # Deliberate responses (404s and friends) — roll back quietly,
            # not as an ERROR with a stack trace (issue #182).
            await session.rollback()
            raise
        except Exception as e:
            logger.exception(f"Database transaction failed: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_all_for_tests() -> None:
    """Create every table directly from the models, bypassing Alembic.

    **Tests only.** Alembic owns the real schema — see ``alembic/versions``
    and the migration step in ``backend/entrypoint.sh``.

    This used to run on every application start as ``init_db()``, which meant
    a fresh deployment got its tables from ``create_all`` with no
    ``alembic_version`` row; the next ``alembic upgrade head`` then tried to
    replay ``001_initial`` against tables that already existed and failed
    (issue #149).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
