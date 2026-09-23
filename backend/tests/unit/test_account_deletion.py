"""Issue #266 — in-app account deletion (App Store Guideline 5.1.1(v)).

``DELETE /api/auth/me`` removes the user and everything stored for them. The
declared ``ondelete="CASCADE"`` rules don't fire on SQLite without
``PRAGMA foreign_keys``, so these tests check every table explicitly.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.routers.auth as auth_module
from app.database import Base
from app.jobs import locks
from app.models import AppSetting, Playlist, PlaylistPodcast, Podcast, Session, SyncLog, User
from app.models.sync_log import SyncStatus
from app.services.account import delete_account


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def fresh_gate(monkeypatch):
    """A gate per test: asyncio.Condition binds to the first loop that waits
    on it, and each test runs on its own loop. Production has one loop."""
    monkeypatch.setattr(locks, "account_write_gate", locks.AccountWriteGate())


async def _add_user(db, spotify_id: str) -> User:
    user = User(
        spotify_id=spotify_id,
        display_name=spotify_id,
        email=f"{spotify_id}@example.com",
        access_token="enc-access",
        refresh_token="enc-refresh",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(user)
    await db.flush()
    return user


async def _seed(db) -> tuple[User, Podcast]:
    """One user with a session, a playlist holding a podcast, a SyncLog row
    and a server setting."""
    user = await _add_user(db, "me")
    podcast = Podcast(spotify_id="show-1", name="Show")
    playlist = Playlist(user_id=user.id, name="Commute")
    db.add_all([podcast, playlist])
    await db.flush()
    db.add_all(
        [
            PlaylistPodcast(playlist_id=playlist.id, podcast_id=podcast.id, position=0),
            Session(
                session_id="sess-1",
                user_id=user.id,
                csrf_token="csrf-1",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            SyncLog(job_type="library_sync", status=SyncStatus.SUCCESS),
            AppSetting(key="playlist_update_hour", value="6"),
        ]
    )
    await db.commit()
    return user, podcast


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


class TestDeleteAccount:
    @pytest.mark.asyncio
    async def test_sole_user_leaves_no_personal_data(self, db):
        user, _ = await _seed(db)

        result = await delete_account(db, user.id)
        await db.commit()

        for model in (User, Session, Playlist, PlaylistPodcast, Podcast, SyncLog):
            assert await _count(db, model) == 0, model.__name__
        assert (result.playlists, result.podcasts, result.sessions) == (1, 1, 1)

    @pytest.mark.asyncio
    async def test_server_settings_survive(self, db):
        user, _ = await _seed(db)

        await delete_account(db, user.id)
        await db.commit()

        assert await _count(db, AppSetting) == 1

    @pytest.mark.asyncio
    async def test_global_tables_kept_while_another_user_remains(self, db):
        """podcasts/sync_logs have no owner; with a second user (a deployment
        that predates the registration lock) they are theirs too."""
        user, podcast = await _seed(db)
        other = await _add_user(db, "other")
        other_playlist = Playlist(user_id=other.id, name="Theirs")
        db.add(other_playlist)
        await db.flush()
        db.add(PlaylistPodcast(playlist_id=other_playlist.id, podcast_id=podcast.id, position=0))
        await db.commit()

        await delete_account(db, user.id)
        await db.commit()

        assert await _count(db, User) == 1
        assert await _count(db, Podcast) == 1
        assert await _count(db, SyncLog) == 1
        assert (await db.execute(select(Playlist.name))).scalars().all() == ["Theirs"]
        assert await _count(db, PlaylistPodcast) == 1


class TestDeleteMeEndpoint:
    @pytest.mark.asyncio
    async def test_deletes_and_clears_cookies(self, db):
        user, _ = await _seed(db)
        response = Response()

        body = await auth_module.delete_me(response=response, session=MagicMock(user_id=user.id), db=db)

        assert "deleted" in body["message"]
        assert await _count(db, User) == 0
        set_cookies = [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]
        assert any(c.startswith("session_id=") and "Max-Age=0" in c for c in set_cookies)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("busy", ["library_sync_lock", "playlist_write_lock"])
    async def test_running_job_is_a_409_and_deletes_nothing(self, db, monkeypatch, busy):
        user, _ = await _seed(db)
        monkeypatch.setattr(auth_module, "ACCOUNT_DELETE_LOCK_WAIT_SECONDS", 0.05)
        lock: asyncio.Lock = getattr(locks, busy)

        await lock.acquire()
        try:
            with pytest.raises(HTTPException) as exc_info:
                await auth_module.delete_me(response=Response(), session=MagicMock(user_id=user.id), db=db)
        finally:
            lock.release()

        assert exc_info.value.status_code == 409
        assert await _count(db, User) == 1
        # Whichever lock was taken before the timeout has been released.
        assert not locks.library_sync_lock.locked()
        assert not locks.playlist_write_lock.locked()


class TestAccountWriteGate:
    """Review on #271: API writes don't take the job locks, so a request that
    validated its session before the delete could insert a row after it."""

    @pytest.mark.asyncio
    async def test_in_flight_write_makes_delete_a_409(self, db, monkeypatch):
        user, _ = await _seed(db)
        monkeypatch.setattr(auth_module, "ACCOUNT_DELETE_LOCK_WAIT_SECONDS", 0.05)

        async with locks.account_write_gate.shared():
            with pytest.raises(HTTPException) as exc_info:
                await auth_module.delete_me(response=Response(), session=MagicMock(user_id=user.id), db=db)

        assert exc_info.value.status_code == 409
        assert await _count(db, User) == 1
        # The gate reopened: a later write gets straight in.
        async with asyncio.timeout(1), locks.account_write_gate.shared():
            pass

    @pytest.mark.asyncio
    async def test_write_arriving_mid_delete_waits_for_it(self):
        gate = locks.AccountWriteGate()
        entered = asyncio.Event()

        async def write():
            async with gate.shared():
                entered.set()

        async with gate.exclusive(timeout=1):
            task = asyncio.create_task(write())
            await asyncio.sleep(0.05)
            assert not entered.is_set()
        await asyncio.wait_for(task, 1)
        assert entered.is_set()

    @pytest.mark.asyncio
    async def test_second_delete_is_refused_while_one_runs(self):
        gate = locks.AccountWriteGate()
        async with gate.exclusive(timeout=1):
            with pytest.raises(TimeoutError):
                async with gate.exclusive(timeout=1):
                    pass


class TestAccountWriteGateMiddleware:
    @staticmethod
    async def _gate_held_during(method: str, path: str) -> bool:
        from app.main import AccountWriteGateMiddleware

        held = {}

        async def inner(scope, receive, send):
            # A closed-for-delete attempt fails fast only if a write is in.
            try:
                async with locks.account_write_gate.exclusive(timeout=0.01):
                    held["value"] = False
            except TimeoutError:
                held["value"] = True

        await AccountWriteGateMiddleware(inner)({"type": "http", "method": method, "path": path}, None, None)
        return held["value"]

    @pytest.mark.asyncio
    async def test_mutating_requests_hold_the_gate(self):
        assert await self._gate_held_during("POST", "/api/playlists") is True
        assert await self._gate_held_during("PATCH", "/api/podcasts/1") is True

    @pytest.mark.asyncio
    async def test_reads_and_the_delete_itself_do_not(self):
        assert await self._gate_held_during("GET", "/api/playlists") is False
        # Holding it would deadlock the delete against its own request.
        assert await self._gate_held_during("DELETE", "/api/auth/me") is False
