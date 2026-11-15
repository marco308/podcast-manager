"""The scheduler instance and the daily update's run times.

The times are stored in ``app_settings`` and turned into one job with an
``OrTrigger`` of ``CronTrigger``s, so several runs a day are still a single
job that APScheduler never runs twice at once.
"""

import contextlib
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_maker
from app.models.settings import AppSetting

# The library sync + rebuild can run up to this many times a day. Each run is
# a full /me/shows walk plus a rebuild of every enabled playlist, so the cap
# keeps the Spotify API budget bounded; one run a day remains the default.
MAX_PLAYLIST_UPDATE_TIMES = 3

# AppSetting key holding the run times as "HH:MM,HH:MM". The older
# ``playlist_update_hour`` / ``playlist_update_minute`` keys are still written
# with the first time, so a downgrade keeps a sensible schedule.
PLAYLIST_UPDATE_TIMES_KEY = "playlist_update_times"

DAILY_UPDATE_JOB_ID = "daily_playlist_update"

logger = logging.getLogger(__name__)
settings = get_settings()

# Global scheduler instance. The run times are wall-clock times in
# ``settings.TIMEZONE`` — the status endpoint reports the zone so the UIs can
# label them, rather than presenting them as the viewer's local time.
scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)


async def upsert_app_setting(db, key: str, value: str) -> None:
    """Insert or update a single ``app_settings`` row. The caller commits."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def normalise_update_times(times: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and de-duplicate run times; reject an empty or oversized list."""
    unique = sorted(set(times))
    if not 1 <= len(unique) <= MAX_PLAYLIST_UPDATE_TIMES:
        raise ValueError(f"Expected 1 to {MAX_PLAYLIST_UPDATE_TIMES} distinct run times, got {len(unique)}")
    return unique


def format_update_times(times: list[tuple[int, int]]) -> str:
    return ",".join(f"{hour:02d}:{minute:02d}" for hour, minute in times)


def _parse_update_times(value: str) -> list[tuple[int, int]]:
    times = []
    for part in value.split(","):
        hour, minute = (int(x) for x in part.strip().split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Run time out of range: {part!r}")
        times.append((hour, minute))
    return normalise_update_times(times)


def update_trigger(times: list[tuple[int, int]]) -> CronTrigger | OrTrigger:
    """One cron trigger per run time, combined — still a single job."""
    triggers = [CronTrigger(hour=hour, minute=minute, timezone=settings.TIMEZONE) for hour, minute in times]
    return triggers[0] if len(triggers) == 1 else OrTrigger(triggers)


def trigger_times(trigger) -> list[tuple[int, int]]:
    """Read the run times back off a live trigger, in time order."""
    crons = trigger.triggers if isinstance(trigger, OrTrigger) else [trigger]
    times = []
    for cron in crons:
        if not isinstance(cron, CronTrigger):
            continue
        hour = settings.PLAYLIST_UPDATE_HOUR
        minute = settings.PLAYLIST_UPDATE_MINUTE
        for field in cron.fields:
            if field.name == "hour":
                with contextlib.suppress(ValueError, TypeError):
                    hour = int(str(field))
            elif field.name == "minute":
                with contextlib.suppress(ValueError, TypeError):
                    minute = int(str(field))
        times.append((hour, minute))
    return sorted(times)


async def load_update_times() -> list[tuple[int, int]]:
    """The persisted run times, falling back to the legacy single-time keys."""
    times = [(settings.PLAYLIST_UPDATE_HOUR, settings.PLAYLIST_UPDATE_MINUTE)]
    try:
        async with async_session_maker() as db:
            result = await db.execute(select(AppSetting).where(AppSetting.key == PLAYLIST_UPDATE_TIMES_KEY))
            times_setting = result.scalar_one_or_none()
            if times_setting:
                return _parse_update_times(times_setting.value)

            result = await db.execute(select(AppSetting).where(AppSetting.key == "playlist_update_hour"))
            hour_setting = result.scalar_one_or_none()
            result = await db.execute(select(AppSetting).where(AppSetting.key == "playlist_update_minute"))
            minute_setting = result.scalar_one_or_none()
            hour = int(hour_setting.value) if hour_setting else times[0][0]
            minute = int(minute_setting.value) if minute_setting else times[0][1]
            times = [(hour, minute)]
    except Exception as e:
        logger.warning(f"Failed to read persisted schedule, using defaults: {e}")
    return times


async def reschedule_playlist_update(times: list[tuple[int, int]]) -> str | None:
    """Reschedule the library sync + playlist update and persist the new times.

    Args:
        times: 1 to ``MAX_PLAYLIST_UPDATE_TIMES`` ``(hour, minute)`` pairs.
            Duplicates are dropped and the list is sorted.

    Returns:
        The next run time as an ISO string, or None if the job has no next
        run (i.e. it is paused). Failures raise rather than returning None —
        the exception carries the reason and is already logged (issue #159).

    Raises:
        ValueError: the list is empty or too long.
        Exception: propagated from APScheduler or the settings write.
    """
    times = normalise_update_times(times)
    try:
        # Persist first, reschedule after: applying the trigger before the
        # write meant a failed write left the live schedule diverging from
        # the persisted one until the next restart (issue #182).
        async with async_session_maker() as db:
            for key, value in [
                (PLAYLIST_UPDATE_TIMES_KEY, format_update_times(times)),
                ("playlist_update_hour", str(times[0][0])),
                ("playlist_update_minute", str(times[0][1])),
            ]:
                await upsert_app_setting(db, key, value)
            await db.commit()

        scheduler.reschedule_job(DAILY_UPDATE_JOB_ID, trigger=update_trigger(times))

        # Get updated next run time
        job = scheduler.get_job(DAILY_UPDATE_JOB_ID)
        next_run = job.next_run_time.isoformat() if job and job.next_run_time else None

        # Log what the live trigger now holds rather than the request's values:
        # it is what will actually run, and it keeps request data out of the log.
        scheduled = format_update_times(trigger_times(job.trigger)) if job else "nothing"
        logger.info(f"Rescheduled daily playlist update to {scheduled}, next run: {next_run}")
        return next_run
    except Exception as e:
        logger.error(f"Failed to reschedule daily playlist update: {e}")
        raise
