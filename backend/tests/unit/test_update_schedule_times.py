"""The library sync + playlist update can run at 1 to 3 times a day.

Still one scheduler job: several times become an ``OrTrigger`` of cron
triggers. The run times persist in ``playlist_update_times``, and the old
single-time keys and response field are kept for installed iOS builds.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.jobs import scheduler
from app.models import Base
from app.models.settings import AppSetting
from app.routers.jobs import UpdateScheduleRequest


@pytest_asyncio.fixture
async def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/schedule.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield session_maker
    finally:
        await engine.dispose()


async def _settings(maker) -> dict[str, str]:
    async with maker() as db:
        rows = (await db.execute(select(AppSetting))).scalars().all()
        return {row.key: row.value for row in rows}


class TestTrigger:
    def test_one_time_is_a_plain_cron_trigger(self):
        assert isinstance(scheduler._update_trigger([(4, 0)]), CronTrigger)

    def test_several_times_fire_at_each(self):
        trigger = scheduler._update_trigger([(4, 0), (13, 30), (19, 15)])
        assert isinstance(trigger, OrTrigger)
        assert scheduler._trigger_times(trigger) == [(4, 0), (13, 30), (19, 15)]

        now = datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
        fires = []
        for _ in range(4):
            now = trigger.get_next_fire_time(None, now)
            fires.append((now.hour, now.minute))
            now = now.replace(second=1)
        assert fires == [(13, 30), (19, 15), (4, 0), (13, 30)]

    def test_times_are_sorted_and_deduplicated(self):
        assert scheduler.normalise_update_times([(13, 0), (4, 0), (13, 0)]) == [(4, 0), (13, 0)]

    @pytest.mark.parametrize("times", [[], [(1, 0), (2, 0), (3, 0), (4, 0)]])
    def test_empty_or_too_many_times_are_rejected(self, times):
        with pytest.raises(ValueError):
            scheduler.normalise_update_times(times)


class TestRequest:
    def test_times_list(self):
        req = UpdateScheduleRequest(times=[{"hour": 13, "minute": 0}, {"hour": 4, "minute": 0}])
        assert req.as_tuples() == [(13, 0), (4, 0)]

    def test_legacy_single_time_from_old_ios_builds(self):
        assert UpdateScheduleRequest(hour=6, minute=30).as_tuples() == [(6, 30)]

    def test_times_wins_over_legacy_fields(self):
        req = UpdateScheduleRequest(times=[{"hour": 7, "minute": 0}], hour=6, minute=30)
        assert req.as_tuples() == [(7, 0)]

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"hour": 6},
            {"times": []},
            {"times": [{"hour": h, "minute": 0} for h in range(4)]},
            {"times": [{"hour": 24, "minute": 0}]},
        ],
    )
    def test_invalid_bodies_are_rejected(self, body):
        with pytest.raises(ValidationError):
            UpdateScheduleRequest(**body)


class TestPersistence:
    @pytest.mark.asyncio
    async def test_reschedule_persists_the_list_and_the_legacy_keys(self, maker):
        fake_scheduler = MagicMock()
        with (
            patch.object(scheduler, "async_session_maker", maker),
            patch.object(scheduler, "scheduler", fake_scheduler),
        ):
            await scheduler.reschedule_playlist_update([(19, 0), (7, 30)])

        assert await _settings(maker) == {
            "playlist_update_times": "07:30,19:00",
            "playlist_update_hour": "7",
            "playlist_update_minute": "30",
        }
        trigger = fake_scheduler.reschedule_job.call_args.kwargs["trigger"]
        assert scheduler._trigger_times(trigger) == [(7, 30), (19, 0)]

    @pytest.mark.asyncio
    async def test_load_reads_the_list(self, maker):
        async with maker() as db:
            db.add(AppSetting(key="playlist_update_times", value="04:00,16:00"))
            db.add(AppSetting(key="playlist_update_hour", value="9"))
            await db.commit()
        with patch.object(scheduler, "async_session_maker", maker):
            assert await scheduler._load_update_times() == [(4, 0), (16, 0)]

    @pytest.mark.asyncio
    async def test_load_falls_back_to_the_legacy_keys(self, maker):
        """A database from before this change has only hour/minute."""
        async with maker() as db:
            db.add(AppSetting(key="playlist_update_hour", value="5"))
            db.add(AppSetting(key="playlist_update_minute", value="45"))
            await db.commit()
        with patch.object(scheduler, "async_session_maker", maker):
            assert await scheduler._load_update_times() == [(5, 45)]


@pytest.mark.asyncio
async def test_status_reports_every_time_and_keeps_the_legacy_field(maker):
    job = SimpleNamespace(
        id="daily_playlist_update",
        name="Daily Library Sync & Playlist Update",
        next_run_time=None,
        trigger=scheduler._update_trigger([(4, 0), (16, 30)]),
    )
    fake_scheduler = MagicMock()
    fake_scheduler.get_jobs.return_value = [job]
    with (
        patch.object(scheduler, "async_session_maker", maker),
        patch.object(scheduler, "scheduler", fake_scheduler),
    ):
        [info] = await scheduler.get_job_status()

    assert info["type"] == "cron"
    assert info["is_configurable"] is True
    assert info["schedule"] == {"hour": 4, "minute": 0}
    assert info["schedule_times"] == [{"hour": 4, "minute": 0}, {"hour": 16, "minute": 30}]
    assert info["max_schedule_times"] == 3
