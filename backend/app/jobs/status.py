"""What the jobs endpoint reports about each scheduled job."""

import logging
from datetime import UTC, datetime

from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.database import async_session_maker
from app.jobs import schedule
from app.jobs.cleanup import CLEANUP_JOB_TYPE
from app.jobs.playlist_update import LIBRARY_SYNC_JOB_TYPE, PLAYLIST_UPDATE_JOB_TYPE
from app.models.sync_log import SyncLog, SyncStatus

logger = logging.getLogger(__name__)

# In-memory last run times, for the interval jobs only: the jobs in
# _SYNCLOG_JOB_TYPES take theirs from the SyncLog table.
_last_run_times: dict[str, datetime] = {}

# The SyncLog job types each scheduler job's runs are recorded under. Last runs
# are read from the table so they survive a restart; the in-memory
# _last_run_times only covers the current process (issue #248).
#
# A job can have more than one: the daily run syncs the library and then
# rebuilds, and each step writes its own row. The UI shows one line per job, so
# the reported status is the worst of a job's steps — otherwise a failed
# library sync under a successful rebuild rendered as a clean run (issue #240).
_SYNCLOG_JOB_TYPES: dict[str, tuple[str, ...]] = {
    schedule.DAILY_UPDATE_JOB_ID: (PLAYLIST_UPDATE_JOB_TYPE, LIBRARY_SYNC_JOB_TYPE),
    "remove_played_episodes": (CLEANUP_JOB_TYPE,),
}


def record_run(job_id: str) -> None:
    """Record the current time as the last run of an interval job."""
    _last_run_times[job_id] = datetime.now(UTC)


async def get_job_status() -> list[dict]:
    """Get status of all scheduled jobs with enhanced info."""
    settings = schedule.settings
    jobs = schedule.scheduler.get_jobs()

    # Last run of each SyncLog-backed job, read from the table so it survives
    # a restart. The status travels with the timestamp so a failed or
    # interrupted run isn't shown as if it worked (issue #161).
    synclog_last_runs: dict[str, tuple[datetime, str]] = {}
    try:
        async with async_session_maker() as db:
            for job_type in {t for types in _SYNCLOG_JOB_TYPES.values() for t in types}:
                row = await db.execute(
                    select(SyncLog).where(SyncLog.job_type == job_type).order_by(SyncLog.started_at.desc()).limit(1)
                )
                last_sync = row.scalar_one_or_none()
                if last_sync and last_sync.started_at:
                    synclog_last_runs[job_type] = (last_sync.started_at, last_sync.status.value)
    except Exception as e:
        # Non-fatal — the job list is still useful without last_run — but
        # don't hide the read failure entirely (issue #182).
        logger.warning(f"Failed to read last job runs from SyncLog: {e}")

    result = []
    for job in jobs:
        info: dict = {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "last_run": None,
            "last_run_status": None,
            "type": "unknown",
            "is_configurable": False,
        }

        # Determine job type and add specific fields
        if isinstance(job.trigger, CronTrigger | OrTrigger):
            info["type"] = "cron"
            times = schedule.trigger_times(job.trigger) or [
                (settings.PLAYLIST_UPDATE_HOUR, settings.PLAYLIST_UPDATE_MINUTE)
            ]
            # ``schedule`` is the first time, kept for installed iOS builds that
            # only know about one; ``schedule_times`` is the full list.
            info["schedule"] = {"hour": times[0][0], "minute": times[0][1]}
            info["schedule_times"] = [{"hour": hour, "minute": minute} for hour, minute in times]
            # The zone those hours and minutes are in — not the viewer's.
            info["schedule_timezone"] = settings.TIMEZONE
            info["is_configurable"] = job.id == schedule.DAILY_UPDATE_JOB_ID
            if info["is_configurable"]:
                info["max_schedule_times"] = schedule.MAX_PLAYLIST_UPDATE_TIMES
        elif isinstance(job.trigger, IntervalTrigger):
            info["type"] = "interval"
            # Get interval in minutes
            interval_seconds = job.trigger.interval.total_seconds()
            info["interval_minutes"] = int(interval_seconds / 60)

        # UTCDateTime and record_run both yield aware datetimes, so
        # isoformat() already carries the offset — no manual "Z" (issue #156).
        # SyncLog is the only source for the jobs that write it: a cleanup run
        # stopped by the recency gate writes no row, did no work and has no
        # status, so it must not show up as the last run.
        job_types = _SYNCLOG_JOB_TYPES.get(job.id)
        if job_types is not None:
            runs = {t: synclog_last_runs[t] for t in job_types if t in synclog_last_runs}
            if runs:
                # The steps of one run start in order, so the newest row is the
                # last step that got going — the right "last run" to show.
                newest_at, newest_status = max(runs.values(), key=lambda run: run[0])
                info["last_run"] = newest_at.isoformat()
                # Worst-of-the-steps, and name what failed so the UI can say
                # which half of the daily run went wrong (issue #240).
                failed = sorted(t for t, run in runs.items() if run[1] == SyncStatus.FAILED.value)
                if failed:
                    info["last_run_status"] = SyncStatus.FAILED.value
                    info["last_run_failed_steps"] = failed
                else:
                    info["last_run_status"] = newest_status
        else:
            in_memory_run = _last_run_times.get(job.id)
            info["last_run"] = in_memory_run.isoformat() if in_memory_run else None

        result.append(info)

    return result
