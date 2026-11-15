"""``sync_log_run`` always closes out the SyncLog row it opens (issue #304).

Before it existed each job wrote the RUNNING row and finalised it by hand,
so a new job (or a new exit path) could leave a row RUNNING until the next
restart's sweep.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.jobs.sync_log import sync_log_run
from app.models import Base
from app.models.sync_log import SyncLog, SyncStatus
from tests.job_patches import patch_job_sessions


@pytest_asyncio.fixture
async def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/runs.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        with patch_job_sessions(session_maker):
            yield session_maker
    finally:
        await engine.dispose()


def _blow_up(message: str) -> None:
    """Raise from a helper, so the code after ``pytest.raises`` isn't read as
    unreachable by static analysis (it runs: pytest.raises swallows this)."""
    raise RuntimeError(message)


async def _only_row(maker) -> SyncLog:
    async with maker() as db:
        [row] = (await db.execute(select(SyncLog))).scalars().all()
        return row


@pytest.mark.asyncio
async def test_row_is_running_inside_the_block_and_finalised_after(maker):
    async with sync_log_run("cleanup") as run:
        assert (await _only_row(maker)).status is SyncStatus.RUNNING
        run.finish(
            status=SyncStatus.SUCCESS,
            details="done",
            failure_code=None,
            playlists_attempted=3,
            playlists_failed=0,
            api_calls_used=7,
        )

    row = await _only_row(maker)
    assert row.id == run.id
    assert row.job_type == "cleanup"
    assert row.status is SyncStatus.SUCCESS
    assert row.details == "done"
    assert (row.playlists_attempted, row.playlists_failed, row.api_calls_used) == (3, 0, 7)
    assert row.completed_at is not None


@pytest.mark.asyncio
async def test_an_exception_fails_the_row_and_propagates(maker):
    with pytest.raises(RuntimeError, match="kaboom"):
        async with sync_log_run("playlist_update"):
            _blow_up("kaboom")

    row = await _only_row(maker)
    assert row.status is SyncStatus.FAILED
    assert row.failure_code == "unknown"
    assert "kaboom" in row.details


@pytest.mark.asyncio
async def test_an_outcome_recorded_before_the_exception_is_kept(maker):
    with pytest.raises(RuntimeError):
        async with sync_log_run("playlist_update") as run:
            run.fail("Failed reading users: db down")
            _blow_up("later")

    assert (await _only_row(maker)).details == "Failed reading users: db down"


@pytest.mark.asyncio
async def test_a_block_that_records_nothing_still_closes_the_row(maker):
    async with sync_log_run("library_sync"):
        pass

    row = await _only_row(maker)
    assert row.status is SyncStatus.FAILED
    assert row.completed_at is not None


@pytest.mark.asyncio
async def test_the_job_still_runs_when_the_row_cannot_be_created():
    def _broken_maker():
        raise RuntimeError("db down")

    ran = False
    with patch_job_sessions(_broken_maker):
        async with sync_log_run("cleanup") as run:
            ran = True
            run.fail("whatever")
    assert ran
    assert run.id is None
