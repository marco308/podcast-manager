"""Startup sweep for SyncLog rows orphaned by a process crash (issue #161).

``update_all_playlists`` and the cleanup job both write a ``RUNNING`` row
first and finalise it last. Issue #174 closed every in-process exit path,
but a process that dies mid-run (deploy, OOM, reboot) never reaches the
finalisation, and the row stayed ``RUNNING`` forever. ``get_job_status``
then reported it as the most recent run with no hint that it never
finished.

The jobs run in-process, so nothing can be running when the scheduler
starts: every ``RUNNING`` row at that moment is an orphan. These tests run
the sweep against a real (temporary) SQLite database so the UPDATE and the
status enum round-trip are exercised for real, not through a fake session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — registers every table on Base.metadata
from app.database import Base
from app.jobs import scheduler
from app.models.sync_log import SyncLog, SyncStatus


@pytest_asyncio.fixture
async def session_maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sweep.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


def _row(job_type: str, status: SyncStatus, *, minutes_ago: int) -> SyncLog:
    started = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    completed = None if status == SyncStatus.RUNNING else started + timedelta(minutes=1)
    return SyncLog(job_type=job_type, status=status, started_at=started, completed_at=completed)


async def _seed(maker, *rows: SyncLog) -> None:
    async with maker() as db:
        db.add_all(rows)
        await db.commit()


async def _all_rows(maker) -> list[SyncLog]:
    async with maker() as db:
        result = await db.execute(select(SyncLog).order_by(SyncLog.id))
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_running_rows_are_marked_failed_and_interrupted(session_maker):
    await _seed(
        session_maker,
        _row("playlist_update", SyncStatus.RUNNING, minutes_ago=90),
        _row("cleanup", SyncStatus.RUNNING, minutes_ago=5),
    )

    with patch.object(scheduler, "async_session_maker", session_maker):
        swept = await scheduler.fail_orphaned_sync_logs()

    assert swept == 2
    rows = await _all_rows(session_maker)
    assert [r.status for r in rows] == [SyncStatus.FAILED, SyncStatus.FAILED]
    for row in rows:
        assert row.failure_code == scheduler.INTERRUPTED_FAILURE_CODE
        assert row.completed_at is not None
        assert row.completed_at >= row.started_at
        assert "interrupted" in row.details.lower()


@pytest.mark.asyncio
async def test_finished_rows_are_left_alone(session_maker):
    await _seed(
        session_maker,
        _row("playlist_update", SyncStatus.SUCCESS, minutes_ago=60),
        _row("playlist_update", SyncStatus.FAILED, minutes_ago=30),
        _row("cleanup", SyncStatus.SUCCESS, minutes_ago=1),
    )
    before = [(r.status, r.completed_at, r.details, r.failure_code) for r in await _all_rows(session_maker)]

    with patch.object(scheduler, "async_session_maker", session_maker):
        swept = await scheduler.fail_orphaned_sync_logs()

    assert swept == 0
    after = [(r.status, r.completed_at, r.details, r.failure_code) for r in await _all_rows(session_maker)]
    assert after == before


@pytest.mark.asyncio
async def test_sweep_is_a_noop_on_an_empty_table(session_maker):
    with patch.object(scheduler, "async_session_maker", session_maker):
        assert await scheduler.fail_orphaned_sync_logs() == 0


@pytest.mark.asyncio
async def test_get_job_status_reports_the_swept_run_as_failed(session_maker):
    """The UI symptom: an interrupted run must not look like a good one."""
    await _seed(session_maker, _row("playlist_update", SyncStatus.RUNNING, minutes_ago=10))

    job = MagicMock()
    job.id = "daily_playlist_update"
    job.name = "Daily Playlist Update"
    job.next_run_time = None
    job.trigger = scheduler.CronTrigger(hour=4, minute=0)
    fake_scheduler = MagicMock()
    fake_scheduler.get_jobs.return_value = [job]

    with (
        patch.object(scheduler, "async_session_maker", session_maker),
        patch.object(scheduler, "scheduler", fake_scheduler),
    ):
        before = await scheduler.get_job_status()
        await scheduler.fail_orphaned_sync_logs()
        after = await scheduler.get_job_status()

    assert before[0]["last_run"] is not None
    assert before[0]["last_run_status"] == "running"
    assert after[0]["last_run"] == before[0]["last_run"]  # started_at is unchanged...
    assert after[0]["last_run_status"] == "failed"  # ...but it is no longer presented as live


@pytest.mark.asyncio
async def test_init_scheduler_runs_the_sweep_before_starting(session_maker):
    await _seed(session_maker, _row("playlist_update", SyncStatus.RUNNING, minutes_ago=10))

    fake_scheduler = MagicMock()
    fake_scheduler.running = False

    with (
        patch.object(scheduler, "async_session_maker", session_maker),
        patch.object(scheduler, "scheduler", fake_scheduler),
    ):
        await scheduler.init_scheduler()

    assert fake_scheduler.start.called
    rows = await _all_rows(session_maker)
    assert rows[0].status == SyncStatus.FAILED


@pytest.mark.asyncio
async def test_a_failing_sweep_does_not_block_startup():
    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    boom = AsyncMock(side_effect=RuntimeError("db exploded"))

    # The schedule read also hits the DB; make it fail too so the test
    # doesn't depend on a real database at all.
    broken_maker = MagicMock(side_effect=RuntimeError("no db"))

    with (
        patch.object(scheduler, "fail_orphaned_sync_logs", boom),
        patch.object(scheduler, "async_session_maker", broken_maker),
        patch.object(scheduler, "scheduler", fake_scheduler),
    ):
        await scheduler.init_scheduler()

    assert boom.await_count == 1
    assert fake_scheduler.start.called
