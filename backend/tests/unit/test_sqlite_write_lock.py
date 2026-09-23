"""No SQLite write transaction may stay open across Spotify calls.

SQLite has one writer. Under pysqlite's default isolation a write transaction
opens on the first flushed INSERT/UPDATE/DELETE and lasts until commit, and
any other connection's write waits out the busy timeout and then fails with
"database is locked".

Two paths used to hold it for minutes:

- ``get_current_session`` flushed ``last_accessed_at`` on every authenticated
  request, so a manual run or library sync held the lock for its whole run of
  Spotify calls.
- ``PlaylistBuilder.update_playlist`` flushed ``last_updated_at`` and left the
  commit to the caller, after *all* of a user's playlists.

Meanwhile ``TokenManager`` commits a rotated PKCE refresh token through its
own session; that commit timed out and the token was lost. These tests run
against a real file-backed database and check that a second connection can
commit while the first is still mid-request / mid-run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Playlist, Session, User
from app.services.playlist_builder import PlaylistBuilder
from app.services.session import SessionService


@pytest_asyncio.fixture
async def dbs(tmp_path):
    """A "request" session and an "other writer" with a short busy timeout."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'lock.db'}"
    engine = create_async_engine(url)
    other_engine = create_async_engine(url, connect_args={"timeout": 0.2})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    other_maker = async_sessionmaker(other_engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as db:
        db.add(
            User(
                id=1,
                spotify_id="me",
                access_token="enc-access",
                refresh_token="enc-refresh",
                token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await db.commit()

    async def other_write(value: str = "rotated") -> None:
        """What TokenManager does: its own session, a write, a commit."""
        async with other_maker() as other:
            await other.execute(text("UPDATE users SET refresh_token = :v WHERE id = 1"), {"v": value})
            await other.commit()

    async with maker() as db:
        yield db, other_write
    await engine.dispose()
    await other_engine.dispose()


async def _add_session(db, last_accessed_at: datetime) -> Session:
    session = Session(
        session_id="sess-1",
        user_id=1,
        csrf_token="csrf-1",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_accessed_at=last_accessed_at,
    )
    db.add(session)
    await db.commit()
    return session


@pytest.mark.asyncio
async def test_harness_detects_a_held_write_lock(dbs):
    """Control: a flushed, uncommitted write does block the other writer."""
    db, other_write = dbs
    await db.execute(text("UPDATE users SET display_name = 'x' WHERE id = 1"))
    with pytest.raises(OperationalError, match="database is locked"):
        await other_write()
    await db.rollback()


class TestLastAccessed:
    @pytest.mark.asyncio
    async def test_stale_timestamp_is_committed_without_holding_the_lock(self, dbs):
        db, other_write = dbs
        stale = datetime.now(UTC) - timedelta(hours=1)
        session = await _add_session(db, stale)

        service = SessionService()
        found = await service.get_session(db, "sess-1")
        await service.update_last_accessed(db, found)

        # The request is still open (the handler hasn't returned), yet
        # another connection can write.
        await other_write()
        assert session.last_accessed_at > stale
        assert found.csrf_token == "csrf-1"

    @pytest.mark.asyncio
    async def test_recent_timestamp_is_not_rewritten(self, dbs):
        db, other_write = dbs
        recent = datetime.now(UTC) - timedelta(seconds=30)
        session = await _add_session(db, recent)

        await SessionService().update_last_accessed(db, session)

        assert session.last_accessed_at == recent
        assert not db.dirty
        await other_write()


def _builder(db, user: User, on_build) -> PlaylistBuilder:
    token_manager = MagicMock()
    token_manager.get_token = AsyncMock(return_value="token")
    token_manager.force_refresh = AsyncMock(return_value="token")
    builder = PlaylistBuilder(db, user, token_manager=token_manager)
    spotify = MagicMock()
    spotify.replace_playlist_items = AsyncMock()
    builder._get_spotify_client = AsyncMock(return_value=spotify)
    builder._build_playlist_content = AsyncMock(side_effect=on_build)
    return builder


async def _seed_playlists(db) -> User:
    db.add_all(
        [
            Playlist(id=1, user_id=1, name="First", spotify_playlist_id="sp-1"),
            Playlist(id=2, user_id=1, name="Second", spotify_playlist_id="sp-2"),
        ]
    )
    await db.commit()
    return (await db.execute(select(User).where(User.id == 1))).scalar_one()


class TestPlaylistRun:
    @pytest.mark.asyncio
    async def test_next_playlists_spotify_calls_run_without_the_lock(self, dbs):
        """While the second playlist is building (Spotify calls), the first
        playlist's write must already be committed, not pending."""
        db, other_write = dbs
        user = await _seed_playlists(db)

        async def on_build(playlist):
            if playlist.id == 2:
                await other_write()  # e.g. a token refresh mid-run
            return ["spotify:episode:a"], []

        results = await _builder(db, user, on_build).update_all_playlists()

        assert [r.success for r in results] == [True, True]
        rows = (await db.execute(text("SELECT last_updated_at FROM playlists ORDER BY id"))).all()
        assert all(row[0] is not None for row in rows)

    @pytest.mark.asyncio
    async def test_one_playlists_db_error_does_not_poison_the_rest(self, dbs):
        db, other_write = dbs
        user = await _seed_playlists(db)

        async def on_build(playlist):
            if playlist.id == 1:
                playlist.user_id = None  # NOT NULL — the commit will fail
            return ["spotify:episode:a"], []

        results = await _builder(db, user, on_build).update_all_playlists()

        assert [(r.playlist_name, r.success) for r in results] == [("First", False), ("Second", True)]
        rows = dict((await db.execute(text("SELECT name, last_updated_at FROM playlists"))).all())
        assert rows["First"] is None
        assert rows["Second"] is not None
        await other_write()
