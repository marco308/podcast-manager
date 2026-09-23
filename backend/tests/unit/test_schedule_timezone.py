"""The playlist update times are wall-clock times in the TIMEZONE setting.

The scheduler used to run in the server's zone (UTC in the container) while
the web UI presented the hour and minute as the browser's local time, so a
UK user who picked 06:00 got a 07:00 run all summer. The zone is now a
setting, applied to every cron trigger and reported by the status endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.jobs import scheduler
from app.models import Base


@pytest_asyncio.fixture
async def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/tz.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, SPOTIFY_CLIENT_ID="x", SPOTIFY_CLIENT_SECRET="x", ENCRYPTION_KEY="x", **overrides)


class TestSetting:
    def test_defaults_to_utc(self, monkeypatch):
        monkeypatch.delenv("TIMEZONE", raising=False)
        assert _settings().TIMEZONE == "UTC"

    def test_accepts_an_iana_name(self):
        assert _settings(TIMEZONE=" Europe/London ").TIMEZONE == "Europe/London"

    @pytest.mark.parametrize("bad", ["Mars/Olympus", "BST", "", "../etc/passwd"])
    def test_rejects_an_unknown_zone(self, bad):
        with pytest.raises(ValidationError, match="TIMEZONE"):
            _settings(TIMEZONE=bad)


class TestTriggers:
    def test_every_trigger_uses_the_configured_zone(self):
        with patch.object(scheduler.settings, "TIMEZONE", "Europe/London"):
            trigger = scheduler._update_trigger([(6, 0), (18, 0)])
        for cron in trigger.triggers:
            assert str(cron.timezone) == "Europe/London"

    def test_six_am_london_in_summer_is_five_utc(self):
        with patch.object(scheduler.settings, "TIMEZONE", "Europe/London"):
            trigger = scheduler._update_trigger([(6, 0)])
        fire = trigger.get_next_fire_time(None, datetime(2026, 7, 1, 0, 0, tzinfo=UTC))
        assert fire.astimezone(ZoneInfo("Europe/London")).hour == 6
        assert fire.astimezone(UTC).hour == 5

    def test_six_am_london_in_winter_is_six_utc(self):
        with patch.object(scheduler.settings, "TIMEZONE", "Europe/London"):
            trigger = scheduler._update_trigger([(6, 0)])
        fire = trigger.get_next_fire_time(None, datetime(2026, 12, 1, 0, 0, tzinfo=UTC))
        assert fire.astimezone(UTC).hour == 6

    def test_times_read_back_unchanged(self):
        """The reported hour and minute are the zone's wall clock, not UTC."""
        with patch.object(scheduler.settings, "TIMEZONE", "America/New_York"):
            trigger = scheduler._update_trigger([(6, 0), (21, 30)])
        assert scheduler._trigger_times(trigger) == [(6, 0), (21, 30)]


@pytest.mark.asyncio
async def test_status_reports_the_zone(maker):
    with patch.object(scheduler.settings, "TIMEZONE", "Europe/London"):
        job = SimpleNamespace(
            id="daily_playlist_update",
            name="Daily Library Sync & Playlist Update",
            next_run_time=None,
            trigger=scheduler._update_trigger([(6, 0)]),
        )
        fake_scheduler = MagicMock()
        fake_scheduler.get_jobs.return_value = [job]
        with (
            patch.object(scheduler, "async_session_maker", maker),
            patch.object(scheduler, "scheduler", fake_scheduler),
        ):
            [info] = await scheduler.get_job_status()

    assert info["schedule_timezone"] == "Europe/London"
    # Existing fields are unchanged for installed iOS builds.
    assert info["schedule"] == {"hour": 6, "minute": 0}
    assert info["schedule_times"] == [{"hour": 6, "minute": 0}]
