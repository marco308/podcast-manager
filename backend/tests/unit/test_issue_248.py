"""API consistency fixes (issue #248).

- ``/podcasts/{podcast_id}`` is keyed by the integer id, like the assignment
  routes, with a Spotify-ID fallback for older iOS builds.
- The cleanup job's last run comes from SyncLog, so it survives a restart
  instead of showing "—" while the history exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — registers every table on Base.metadata
from app.database import Base
from app.jobs import scheduler
from app.models import Podcast
from app.models.sync_log import SyncLog, SyncStatus
from app.routers.podcasts import get_podcast, update_podcast
from app.schemas.podcast import PodcastUpdate


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _seed_podcast(maker) -> None:
    async with maker() as db:
        db.add(Podcast(spotify_id="4rOoJ6Egrf8K2IrywzwOMk", name="Show", total_episodes=1, unplayed_episodes=0))
        await db.commit()


class TestPodcastRouteKey:
    @pytest.mark.asyncio
    async def test_integer_id_is_the_key(self, maker):
        await _seed_podcast(maker)
        async with maker() as db:
            response = await get_podcast(podcast_id="1", user_id=1, db=db)
            assert response.id == 1
            assert response.spotify_id == "4rOoJ6Egrf8K2IrywzwOMk"

            updated = await update_podcast(
                podcast_id="1", update_data=PodcastUpdate(is_sequential=True), session=SimpleNamespace(user_id=1), db=db
            )
            assert updated.is_sequential is True

    @pytest.mark.asyncio
    async def test_spotify_id_still_resolves_for_old_clients(self, maker):
        await _seed_podcast(maker)
        async with maker() as db:
            response = await get_podcast(podcast_id="4rOoJ6Egrf8K2IrywzwOMk", user_id=1, db=db)
            assert response.id == 1

    @pytest.mark.asyncio
    async def test_unknown_id_is_404(self, maker):
        await _seed_podcast(maker)
        async with maker() as db:
            with pytest.raises(HTTPException) as exc_info:
                await get_podcast(podcast_id="99", user_id=1, db=db)
            assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_cleanup_last_run_survives_a_restart(maker):
    started = datetime.now(UTC) - timedelta(minutes=5)
    async with maker() as db:
        db.add(
            SyncLog(
                job_type="cleanup",
                status=SyncStatus.FAILED,
                started_at=started,
                completed_at=started + timedelta(minutes=1),
            )
        )
        await db.commit()

    job = MagicMock()
    job.id = "remove_played_episodes"
    job.name = "Remove Played Episodes"
    job.next_run_time = None
    job.trigger = IntervalTrigger(minutes=30)
    fake_scheduler = MagicMock()
    fake_scheduler.get_jobs.return_value = [job]

    # A fresh process: nothing recorded in memory yet.
    with (
        patch.object(scheduler, "async_session_maker", maker),
        patch.object(scheduler, "scheduler", fake_scheduler),
        patch.object(scheduler, "_last_run_times", {}),
    ):
        [info] = await scheduler.get_job_status()

    assert datetime.fromisoformat(info["last_run"]) == started
    assert info["last_run_status"] == "failed"
