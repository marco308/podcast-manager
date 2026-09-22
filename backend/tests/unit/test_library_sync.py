"""The library sync as a scheduled, shared, serialised job (issue #240).

The reconcile itself — marking, the grace period, what counts as a complete
walk — is issue #155's and is covered by ``test_sync_podcasts_issue155.py``,
which still drives it through ``POST /podcasts/sync``. This file covers what
#240 adds on top:

- a marked show stops contributing episodes *now*, not when its row is
  finally deleted at the end of the grace period;
- the sync runs on a schedule at all, as the first step of the daily job,
  under its own SyncLog job type and without being able to abort the rebuild;
- the daily job's reported status can't hide a failed sync behind a
  successful rebuild;
- two concurrent syncs can't race each other onto the unique constraint.
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


def _show(spotify_id):
    return {"show": {"id": spotify_id, "name": spotify_id, "images": [], "publisher": "pub", "total_episodes": 3}}


def _podcast(spotify_id, **kwargs):
    return Podcast(spotify_id=spotify_id, name=spotify_id, total_episodes=3, **kwargs)


def _page(*show_ids, total=None):
    """One ``GET /me/shows`` page. ``total`` defaults to the page's own size."""
    items = [_show(s) for s in show_ids]
    return {"items": items, "total": len(items) if total is None else total}


def _spotify_returning(*pages):
    client = MagicMock()
    client.get_user_shows = AsyncMock(side_effect=list(pages))
    return client


class TestMarkedShowStopsContributing:
    """#155 marks the show but left it in builds for the whole grace period."""

    @pytest.mark.asyncio
    async def test_marked_podcast_is_left_out_of_a_build(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                user = _user()
                db.add(user)
                await db.flush()
                subscribed = _podcast("subscribed")
                gone = _podcast("gone", missing_since=datetime.now(UTC))
                playlist = Playlist(user_id=user.id, name="Commute")
                db.add_all([subscribed, gone, playlist])
                await db.flush()
                db.add_all(
                    [
                        PlaylistPodcast(playlist_id=playlist.id, podcast_id=subscribed.id, position=1),
                        PlaylistPodcast(playlist_id=playlist.id, podcast_id=gone.id, position=2),
                    ]
                )
                await db.commit()

                builder = PlaylistBuilder(db, user, token_manager=MagicMock())
                entries = await builder._get_playlist_podcasts(playlist.id)

                assert [e.podcast.spotify_id for e in entries] == ["subscribed"]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_the_assignment_survives_so_resubscribing_restores_it(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                user = _user()
                db.add(user)
                await db.flush()
                gone = _podcast("gone", missing_since=datetime.now(UTC))
                playlist = Playlist(user_id=user.id, name="Commute")
                db.add_all([gone, playlist])
                await db.flush()
                db.add(PlaylistPodcast(playlist_id=playlist.id, podcast_id=gone.id, position=1))
                await db.commit()

                builder = PlaylistBuilder(db, user, token_manager=MagicMock())
                assert await builder._get_playlist_podcasts(playlist.id) == []

                # The upsert loop clears the mark when the show comes back.
                gone.missing_since = None
                await db.commit()

                entries = await builder._get_playlist_podcasts(playlist.id)
                assert [e.podcast.spotify_id for e in entries] == ["gone"]
        finally:
            await engine.dispose()


class TestSyncEndpoint:
    @pytest.mark.asyncio
    async def test_skipped_reconcile_is_reported(self, monkeypatch):
        """A walk that lost a page reconciles nothing, and the response has to
        say so: the counts don't mean what they usually mean."""
        engine, maker = await _make_db()
        monkeypatch.setattr(
            podcasts_module,
            "SpotifyService",
            MagicMock(return_value=_spotify_returning(_page("a", total=9))),
        )
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

                assert result["reconcile_skipped"] is True
                assert result["missing"] == 0
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_complete_walk_is_not_reported_as_skipped(self, monkeypatch):
        engine, maker = await _make_db()
        monkeypatch.setattr(
            podcasts_module,
            "SpotifyService",
            MagicMock(return_value=_spotify_returning(_page("a"))),
        )
        try:
            async with maker() as db:
                db.add(_user())
                await db.commit()

                result = await sync_podcasts(
                    request=MagicMock(),
                    session=SimpleNamespace(user_id=1),
                    db=db,
                )

                assert result["reconcile_skipped"] is False
                assert result["synced"] == 1
        finally:
            await engine.dispose()


class TestConcurrentSyncsAreSerialised:
    @pytest.mark.asyncio
    async def test_manual_sync_is_rejected_while_another_holds_the_lock(self, monkeypatch):
        """Two concurrent walks both insert a newly-followed show; the loser's
        commit dies on the unique constraint and sinks the whole sync."""
        engine, maker = await _make_db()
        monkeypatch.setattr(podcasts_module, "SYNC_LOCK_WAIT_SECONDS", 0.05)
        monkeypatch.setattr(
            podcasts_module,
            "SpotifyService",
            MagicMock(return_value=_spotify_returning(_page())),
        )
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
            return _page()

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


class TestLibrarySyncJob:
    @pytest.mark.asyncio
    async def test_job_marks_a_missing_show_and_records_its_own_synclog_row(self):
        """Nothing used to advance the #155 reconcile without a button press."""
        engine, maker = await _make_db()
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
                patch(
                    "app.jobs.scheduler.SpotifyService",
                    MagicMock(return_value=_spotify_returning(_page("kept"))),
                ),
            ):
                await scheduler.sync_all_libraries()

            async with maker() as db:
                logs = await db.execute(select(SyncLog).where(SyncLog.job_type == "library_sync"))
                row = logs.scalar_one()
                assert row.status is SyncStatus.SUCCESS
                assert "1 no longer subscribed" in row.details

                gone = await db.execute(select(Podcast).where(Podcast.spotify_id == "gone"))
                assert gone.scalar_one().missing_since is not None
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

                kept = await db.execute(select(Podcast).where(Podcast.spotify_id == "kept"))
                assert kept.scalar_one().missing_since is None
        finally:
            await engine.dispose()


class TestJobStatusFoldsInTheSyncStep:
    """The UI shows one line for the daily job, which now runs two steps."""

    @staticmethod
    def _daily_job_info(jobs: list[dict]) -> dict:
        return next(j for j in jobs if j["id"] == "daily_playlist_update")

    @staticmethod
    def _log(job_type: str, status: SyncStatus, minute: int) -> SyncLog:
        return SyncLog(
            job_type=job_type,
            status=status,
            started_at=datetime(2026, 9, 22, 3, minute, tzinfo=UTC),
        )

    @pytest.mark.asyncio
    async def test_failed_sync_under_a_successful_rebuild_is_reported(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add_all(
                    [
                        self._log("library_sync", SyncStatus.FAILED, 0),
                        self._log("playlist_update", SyncStatus.SUCCESS, 5),
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
                        self._log("library_sync", SyncStatus.SUCCESS, 0),
                        self._log("playlist_update", SyncStatus.SUCCESS, 5),
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
