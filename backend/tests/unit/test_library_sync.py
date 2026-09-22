"""Tests for the library sync reconciliation (issue #240).

The sync used to be upsert-only, so a show unfollowed inside Spotify stayed
in the app, stayed assigned to playlists, and kept contributing episodes on
every rebuild (``GET /shows/{id}/episodes`` still works for shows you no
longer follow). It now stamps ``unfollowed_at`` on anything missing from
``GET /me/shows``, the builder skips stamped shows, and the daily job runs
the whole thing so nobody has to press Sync.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.routers.podcasts as podcasts_module
from app.database import Base
from app.jobs import locks, scheduler
from app.models import Playlist, PlaylistPodcast, Podcast, User
from app.models.sync_log import SyncLog, SyncStatus
from app.rate_limit import limiter
from app.routers.podcasts import sync_podcasts
from app.services.encryption import get_encryption_service
from app.services.library_sync import sync_library
from app.services.playlist_builder import PlaylistBuilder


@pytest.fixture(autouse=True)
def _limiter_disabled():
    """Direct route calls still pass through the slowapi wrapper."""
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def _fresh_lock():
    """Fresh sync lock per test — asyncio primitives bind to the running loop."""
    original = locks.library_sync_lock
    locks.library_sync_lock = asyncio.Lock()
    try:
        yield
    finally:
        locks.library_sync_lock = original


async def _make_db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    return engine, maker


def _user():
    encryption = get_encryption_service()
    return User(
        spotify_id="spotify-user",
        access_token=encryption.encrypt("access-token"),
        refresh_token=encryption.encrypt("refresh-token"),
        token_expires_at=datetime.now(UTC),
    )


def _show(spotify_id, name="Show"):
    return {"show": {"id": spotify_id, "name": name, "images": [], "publisher": "pub", "total_episodes": 3}}


def _podcast(spotify_id, name="Show", **kwargs):
    return Podcast(spotify_id=spotify_id, name=name, total_episodes=3, unplayed_episodes=0, **kwargs)


def _spotify_returning(*pages):
    """Client whose ``get_user_shows`` hands back the given pages in order."""
    client = MagicMock()
    client.get_user_shows = AsyncMock(side_effect=[{"items": list(page)} for page in pages])
    return client


async def _unfollowed_at(db, spotify_id):
    row = await db.execute(select(Podcast).where(Podcast.spotify_id == spotify_id))
    return row.scalar_one().unfollowed_at


class TestUnfollowReconciliation:
    @pytest.mark.asyncio
    async def test_podcast_missing_from_spotify_is_stamped(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add_all([_podcast("kept"), _podcast("gone")])
                await db.commit()

                result = await sync_library(db, _spotify_returning([_show("kept")]))
                await db.commit()

                assert result.unfollowed == 1
                assert await _unfollowed_at(db, "gone") is not None
                assert await _unfollowed_at(db, "kept") is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_stamp_is_not_reapplied_on_a_second_run(self):
        """The stamp records when the show went, not when we last looked."""
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_podcast("gone"))
                await db.commit()

                await sync_library(db, _spotify_returning([]))
                await db.commit()
                first = await _unfollowed_at(db, "gone")

                second_result = await sync_library(db, _spotify_returning([]))
                await db.commit()

                assert second_result.unfollowed == 0
                assert await _unfollowed_at(db, "gone") == first
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_refollowed_podcast_is_cleared_with_assignments_intact(self):
        """Re-following restores the show to its playlists untouched."""
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                user = _user()
                db.add(user)
                await db.flush()
                podcast = _podcast("back", unfollowed_at=datetime.now(UTC))
                playlist = Playlist(user_id=user.id, name="Commute")
                db.add_all([podcast, playlist])
                await db.flush()
                db.add(PlaylistPodcast(playlist_id=playlist.id, podcast_id=podcast.id, position=1))
                await db.commit()

                result = await sync_library(db, _spotify_returning([_show("back")]))
                await db.commit()

                assert result.refollowed == 1
                assert await _unfollowed_at(db, "back") is None
                assignments = await db.execute(
                    select(PlaylistPodcast).where(PlaylistPodcast.podcast_id == podcast.id)
                )
                assert len(assignments.scalars().all()) == 1
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_empty_library_response_stamps_nothing(self):
        """An empty /me/shows can't be told apart from a broken read.

        Stamping there would take every playlist to nothing on the next
        build, so the run declines to reconcile and leaves it to the next one.
        """
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add_all([_podcast("a"), _podcast("b")])
                await db.commit()

                result = await sync_library(db, _spotify_returning([]))
                await db.commit()

                assert result.reconciled is False
                assert result.unfollowed == 0
                assert await _unfollowed_at(db, "a") is None
                assert await _unfollowed_at(db, "b") is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_empty_library_with_empty_local_library_is_a_clean_run(self):
        """A genuinely empty library is not a glitch — nothing to protect."""
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                result = await sync_library(db, _spotify_returning([]))
                assert result.reconciled is True
                assert result.synced == 0
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_partial_walk_reconciles_nothing(self):
        """A page that fails must not turn the rest of the library into unfollows."""
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add_all([_podcast(f"show{i}") for i in range(60)])
                await db.commit()

                client = MagicMock()
                client.get_user_shows = AsyncMock(
                    side_effect=[
                        {"items": [_show(f"show{i}") for i in range(50)]},
                        RuntimeError("Spotify fell over on page 2"),
                    ]
                )

                with pytest.raises(RuntimeError):
                    await sync_library(db, client)

                await db.rollback()
                assert await _unfollowed_at(db, "show55") is None
        finally:
            await engine.dispose()


class TestBuilderSkipsUnfollowed:
    @pytest.mark.asyncio
    async def test_unfollowed_podcast_contributes_nothing(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                user = _user()
                db.add(user)
                await db.flush()
                followed = _podcast("followed")
                unfollowed = _podcast("unfollowed", unfollowed_at=datetime.now(UTC))
                playlist = Playlist(user_id=user.id, name="Commute")
                db.add_all([followed, unfollowed, playlist])
                await db.flush()
                db.add_all(
                    [
                        PlaylistPodcast(playlist_id=playlist.id, podcast_id=followed.id, position=1),
                        PlaylistPodcast(playlist_id=playlist.id, podcast_id=unfollowed.id, position=2),
                    ]
                )
                await db.commit()

                builder = PlaylistBuilder(db, user, token_manager=MagicMock())
                entries = await builder._get_playlist_podcasts(playlist.id)

                assert [e.podcast.spotify_id for e in entries] == ["followed"]
        finally:
            await engine.dispose()


class TestSyncEndpoint:
    @pytest.mark.asyncio
    async def test_response_reports_the_reconciliation(self, monkeypatch):
        engine, maker = await _make_db()
        client = _spotify_returning([_show("kept")])
        monkeypatch.setattr(podcasts_module, "SpotifyService", MagicMock(return_value=client))
        try:
            async with maker() as db:
                db.add(_user())
                db.add_all([_podcast("kept"), _podcast("gone")])
                await db.commit()

                result = await sync_podcasts(
                    request=MagicMock(),
                    session=SimpleNamespace(user_id=1),
                    db=db,
                )

                assert result["synced"] == 1
                assert result["unfollowed"] == 1
                assert result["unfollow_check_skipped"] is False
                assert await _unfollowed_at(db, "gone") is not None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_skipped_unfollow_check_is_reported(self, monkeypatch):
        """"0 synced" alone would read as a clean sync of an empty library."""
        engine, maker = await _make_db()
        monkeypatch.setattr(podcasts_module, "SpotifyService", MagicMock(return_value=_spotify_returning([])))
        try:
            async with maker() as db:
                db.add(_user())
                db.add(_podcast("still-here"))
                await db.commit()

                result = await sync_podcasts(
                    request=MagicMock(),
                    session=SimpleNamespace(user_id=1),
                    db=db,
                )

                assert result["unfollow_check_skipped"] is True
                assert result["unfollowed"] == 0
        finally:
            await engine.dispose()


class TestLibrarySyncJob:
    @pytest.mark.asyncio
    async def test_job_records_its_own_synclog_row(self):
        """The sync gets its own job_type so the history distinguishes it."""
        engine, maker = await _make_db()
        client = _spotify_returning([_show("kept")])
        token_manager = MagicMock()
        token_manager.get_token = AsyncMock(return_value="token")
        try:
            async with maker() as db:
                db.add(_user())
                db.add_all([_podcast("kept"), _podcast("gone")])
                await db.commit()

            with (
                patch("app.jobs.scheduler.async_session_maker", maker),
                patch("app.jobs.scheduler.TokenManager", MagicMock(return_value=token_manager)),
                patch("app.jobs.scheduler.SpotifyService", MagicMock(return_value=client)),
            ):
                await scheduler.sync_all_libraries()

            async with maker() as db:
                logs = await db.execute(select(SyncLog).where(SyncLog.job_type == "library_sync"))
                row = logs.scalar_one()
                assert row.status is SyncStatus.SUCCESS
                assert "1 unfollowed" in row.details
                assert await _unfollowed_at(db, "gone") is not None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_a_users_failure_is_recorded_and_rolled_back(self):
        engine, maker = await _make_db()
        token_manager = MagicMock()
        token_manager.get_token = AsyncMock(side_effect=RuntimeError("token gone"))
        try:
            async with maker() as db:
                db.add(_user())
                db.add(_podcast("kept"))
                await db.commit()

            with (
                patch("app.jobs.scheduler.async_session_maker", maker),
                patch("app.jobs.scheduler.TokenManager", MagicMock(return_value=token_manager)),
            ):
                await scheduler.sync_all_libraries()

            async with maker() as db:
                logs = await db.execute(select(SyncLog).where(SyncLog.job_type == "library_sync"))
                row = logs.scalar_one()
                assert row.status is SyncStatus.FAILED
                assert "token gone" in row.details
                assert await _unfollowed_at(db, "kept") is None
        finally:
            await engine.dispose()


class TestConcurrentSyncsAreSerialised:
    @pytest.mark.asyncio
    async def test_manual_sync_is_rejected_while_another_holds_the_lock(self, monkeypatch):
        """Two concurrent walks both insert a new show; the loser's commit dies
        on the unique constraint and sinks the whole sync."""
        engine, maker = await _make_db()
        monkeypatch.setattr(podcasts_module, "SYNC_LOCK_WAIT_SECONDS", 0.05)
        monkeypatch.setattr(podcasts_module, "SpotifyService", MagicMock(return_value=_spotify_returning([])))
        try:
            async with maker() as db:
                db.add(_user())
                await db.commit()

                await locks.library_sync_lock.acquire()
                try:
                    with pytest.raises(HTTPException) as exc_info:
                        await sync_podcasts(
                            request=MagicMock(),
                            session=SimpleNamespace(user_id=1),
                            db=db,
                        )
                finally:
                    locks.library_sync_lock.release()

                assert exc_info.value.status_code == 409
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_manual_sync_releases_the_lock_on_failure(self, monkeypatch):
        engine, maker = await _make_db()
        client = MagicMock()
        client.get_user_shows = AsyncMock(side_effect=RuntimeError("Spotify fell over"))
        monkeypatch.setattr(podcasts_module, "SpotifyService", MagicMock(return_value=client))
        try:
            async with maker() as db:
                db.add(_user())
                await db.commit()

                with pytest.raises(RuntimeError):
                    await sync_podcasts(
                        request=MagicMock(),
                        session=SimpleNamespace(user_id=1),
                        db=db,
                    )

                assert not locks.library_sync_lock.locked()
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_job_holds_the_lock_across_the_walk(self):
        engine, maker = await _make_db()
        token_manager = MagicMock()
        token_manager.get_token = AsyncMock(return_value="token")
        held: list[bool] = []

        client = MagicMock()

        async def observe_lock(*_a, **_kw):
            held.append(locks.library_sync_lock.locked())
            return {"items": []}

        client.get_user_shows = observe_lock
        try:
            async with maker() as db:
                db.add(_user())
                await db.commit()

            with (
                patch("app.jobs.scheduler.async_session_maker", maker),
                patch("app.jobs.scheduler.TokenManager", MagicMock(return_value=token_manager)),
                patch("app.jobs.scheduler.SpotifyService", MagicMock(return_value=client)),
            ):
                await scheduler.sync_all_libraries()

            assert held == [True]
            assert not locks.library_sync_lock.locked()
        finally:
            await engine.dispose()


class TestJobStatusFoldsInTheSyncStep:
    """The UI shows one line for the daily job, which now runs two steps."""

    @staticmethod
    def _daily_job_info(jobs: list[dict]) -> dict:
        return next(j for j in jobs if j["id"] == "daily_playlist_update")

    @pytest.mark.asyncio
    async def test_failed_sync_under_a_successful_rebuild_is_reported(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add_all(
                    [
                        SyncLog(
                            job_type="library_sync",
                            status=SyncStatus.FAILED,
                            started_at=datetime(2026, 9, 22, 3, 0, tzinfo=UTC),
                        ),
                        SyncLog(
                            job_type="playlist_update",
                            status=SyncStatus.SUCCESS,
                            started_at=datetime(2026, 9, 22, 3, 5, tzinfo=UTC),
                        ),
                    ]
                )
                await db.commit()

            with patch("app.jobs.scheduler.async_session_maker", maker):
                info = self._daily_job_info(await _job_status_with_daily_job())

            assert info["last_run_status"] == "failed"
            assert info["last_run_failed_steps"] == ["library_sync"]
            # The rebuild is the later step, so it still dates the run.
            assert info["last_run"].startswith("2026-09-22T03:05")
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_both_steps_succeeding_reports_success(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add_all(
                    [
                        SyncLog(
                            job_type="library_sync",
                            status=SyncStatus.SUCCESS,
                            started_at=datetime(2026, 9, 22, 3, 0, tzinfo=UTC),
                        ),
                        SyncLog(
                            job_type="playlist_update",
                            status=SyncStatus.SUCCESS,
                            started_at=datetime(2026, 9, 22, 3, 5, tzinfo=UTC),
                        ),
                    ]
                )
                await db.commit()

            with patch("app.jobs.scheduler.async_session_maker", maker):
                info = self._daily_job_info(await _job_status_with_daily_job())

            assert info["last_run_status"] == "success"
            assert "last_run_failed_steps" not in info
        finally:
            await engine.dispose()


async def _job_status_with_daily_job() -> list[dict]:
    """Run get_job_status against a scheduler holding just the daily job."""
    job = SimpleNamespace(
        id="daily_playlist_update",
        name="Daily Library Sync & Playlist Update",
        next_run_time=None,
        trigger=CronTrigger(hour=3, minute=0),
    )
    with patch.object(scheduler.scheduler, "get_jobs", MagicMock(return_value=[job])):
        return await scheduler.get_job_status()


class TestDailyJobRunsTheSync:
    @pytest.mark.asyncio
    async def test_rebuild_syncs_the_library_first(self):
        """Nothing used to pull /me/shows on a schedule (issue #240)."""
        order: list[str] = []

        async def fake_sync():
            order.append("sync")

        async def fake_finalise(*_a, **_kw):
            order.append("rebuild-finalised")

        with (
            patch("app.jobs.scheduler.sync_all_libraries", fake_sync),
            patch("app.jobs.scheduler._finalise_sync_log", fake_finalise),
            patch("app.jobs.scheduler.async_session_maker", _empty_session_factory()),
        ):
            await scheduler.update_all_playlists()

        assert order == ["sync", "rebuild-finalised"]

    @pytest.mark.asyncio
    async def test_sync_failure_does_not_stop_the_rebuild(self):
        """A stale library beats a day with no playlist update."""
        finalise = AsyncMock()

        async def exploding_sync():
            raise RuntimeError("Spotify unreachable")

        with (
            patch("app.jobs.scheduler.sync_all_libraries", exploding_sync),
            patch("app.jobs.scheduler._finalise_sync_log", finalise),
            patch("app.jobs.scheduler.async_session_maker", _empty_session_factory()),
        ):
            await scheduler.update_all_playlists()

        finalise.assert_awaited_once()
        _args, kwargs = finalise.await_args
        assert kwargs["status"] is SyncStatus.SUCCESS


def _empty_session_factory():
    """Session maker whose every query answers "no rows"."""

    class _Result:
        def scalar_one_or_none(self):
            return None

        def scalars(self):
            inner = MagicMock()
            inner.all.return_value = []
            return inner

        def all(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def execute(self, *_a, **_kw):
            return _Result()

        async def commit(self):
            return None

        async def rollback(self):
            return None

        def add(self, obj):
            # The RUNNING SyncLog row needs an id for the finaliser to find.
            if hasattr(obj, "job_type"):
                obj.id = 1

    return lambda: _Session()
