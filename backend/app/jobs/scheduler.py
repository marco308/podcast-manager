"""APScheduler setup: registers the jobs and starts and stops the scheduler.

The jobs themselves live in their own modules:

- :mod:`app.jobs.schedule` — the scheduler instance and the daily run times
- :mod:`app.jobs.playlist_update` — library sync + playlist rebuild
- :mod:`app.jobs.cleanup` — removing played episodes
- :mod:`app.jobs.status` — what ``GET /jobs/status`` reports
- :mod:`app.jobs.sync_log` — SyncLog run bookkeeping and failure codes

The names below are re-exported so ``main.py`` and the jobs router keep
importing from here.
"""

import logging
from datetime import UTC, datetime

from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.database import async_session_maker
from app.jobs import schedule
from app.jobs.cleanup import remove_played_episodes_from_playlists
from app.jobs.playlist_update import sync_all_libraries, update_all_playlists
from app.jobs.schedule import (
    DAILY_UPDATE_JOB_ID,
    MAX_PLAYLIST_UPDATE_TIMES,
    format_update_times,
    load_update_times,
    reschedule_playlist_update,
    update_trigger,
)
from app.jobs.session_cleanup import cleanup_expired_sessions as _cleanup_expired_sessions
from app.jobs.status import get_job_status, record_run
from app.jobs.sync_log import fail_orphaned_sync_logs
from app.models.user import User
from app.services.token_manager import TokenManager

__all__ = [
    "MAX_PLAYLIST_UPDATE_TIMES",
    "get_job_status",
    "init_scheduler",
    "remove_played_episodes_from_playlists",
    "reschedule_playlist_update",
    "shutdown_scheduler",
    "sync_all_libraries",
    "update_all_playlists",
]

# Token refresh cadence (issue #166). INVARIANT: the refresh threshold MUST
# exceed the job interval. A token with less life left than one interval
# would be skipped by this run and expire before the next one fires, leaving
# the stored access token dead in between — which is exactly what the old
# 900s threshold against a 45-minute interval did (~30 dead minutes in every
# 90). Deriving the threshold from the interval keeps the two from drifting
# apart: 45-minute interval + 5-minute margin → refresh anything with under
# 50 minutes of life remaining.
TOKEN_REFRESH_INTERVAL_MINUTES = 45
TOKEN_REFRESH_MARGIN_MINUTES = 5
TOKEN_REFRESH_THRESHOLD_SECONDS = (TOKEN_REFRESH_INTERVAL_MINUTES + TOKEN_REFRESH_MARGIN_MINUTES) * 60

# How late the daily update may still start after its scheduled time (e.g.
# after an event-loop stall). APScheduler's default of 1s drops the run.
DAILY_UPDATE_MISFIRE_GRACE_SECONDS = 600

logger = logging.getLogger(__name__)


async def cleanup_expired_sessions() -> None:
    """Wrapper around session cleanup that records run time."""
    record_run("session_cleanup")
    await _cleanup_expired_sessions()


async def refresh_all_tokens() -> None:
    """Refresh Spotify tokens for all users before they expire.

    Delegates the refresh to :class:`TokenManager` so it happens under the
    per-user lock, with the refresh token re-read inside it — a snapshot
    taken outside the lock can race a concurrent TokenManager refresh and
    persist a superseded (rotated) refresh token, which Spotify then
    rejects with ``invalid_grant`` (issue #167).
    """
    record_run("token_refresh")
    logger.info("Starting token refresh job")

    # Read user IDs with a short-lived session. Freshness is re-checked
    # inside get_token, so no token state is snapshotted here.
    user_ids: list[int] = []
    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User.id))
            user_ids = [row[0] for row in result.all()]
        except Exception as e:
            logger.error(f"Token refresh job failed reading DB: {e}")
            return

    for user_id in user_ids:
        try:
            await TokenManager(user_id).get_token(min_remaining_seconds=TOKEN_REFRESH_THRESHOLD_SECONDS)
        except Exception as e:
            logger.error(f"Failed to refresh token for user {user_id}: {e}")

    logger.info("Token refresh job completed")


async def init_scheduler() -> None:
    """Initialize and start the scheduler with configured jobs."""
    scheduler = schedule.scheduler
    if scheduler.running:
        return

    # Nothing can be running yet, so any RUNNING row is left over from a
    # process that died mid-job. Close it out before the jobs (and the UI's
    # last-run lookup) can see it.
    try:
        await fail_orphaned_sync_logs()
    except Exception as e:
        logger.error(f"Failed to sweep orphaned SyncLog rows at startup: {e}")

    update_times = await load_update_times()

    # Library sync + playlist rebuild, at each of the configured times (one by
    # default, up to MAX_PLAYLIST_UPDATE_TIMES). The id stays
    # ``daily_playlist_update`` — it is what the persisted schedule, the
    # reschedule endpoint and the UI's "configurable" flag key off — but the
    # name says what the run actually does now (issue #240). max_instances=1
    # (the default) means a run still going when the next time comes round is
    # skipped rather than doubled up. APScheduler's default misfire grace is
    # 1s, so a brief event-loop stall at the scheduled moment would drop the
    # run entirely; 10 minutes of grace plus coalesce runs it late, once. The
    # options live on the job, so they hold for every time in an OrTrigger
    # and survive reschedule_job (which only swaps the trigger).
    scheduler.add_job(
        update_all_playlists,
        update_trigger(update_times),
        id=DAILY_UPDATE_JOB_ID,
        name="Daily Library Sync & Playlist Update",
        replace_existing=True,
        misfire_grace_time=DAILY_UPDATE_MISFIRE_GRACE_SECONDS,
        coalesce=True,
    )

    # Token refresh — the threshold in refresh_all_tokens must stay above
    # this interval (issue #166), see TOKEN_REFRESH_THRESHOLD_SECONDS. First
    # run is at startup rather than one interval in, so a token that lapsed
    # while the server was down is renewed straight away.
    scheduler.add_job(
        refresh_all_tokens,
        IntervalTrigger(minutes=TOKEN_REFRESH_INTERVAL_MINUTES),
        id="token_refresh",
        name="Spotify Token Refresh",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
    )

    # Remove played episodes every 30 minutes (issue #89, PR2).
    # The previous 5-minute cadence — combined with a per-episode
    # GET /episodes/{id} fan-out — was the rate-limit culprit. We now
    # filter played episodes directly from the playlist-items page and
    # back the cadence off; misfire_grace_time + coalesce + max_instances
    # keep things tidy if a run overruns.
    scheduler.add_job(
        remove_played_episodes_from_playlists,
        IntervalTrigger(minutes=30),
        id="remove_played_episodes",
        name="Remove Played Episodes",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    # Session cleanup every hour
    scheduler.add_job(
        cleanup_expired_sessions,
        IntervalTrigger(hours=1),
        id="session_cleanup",
        name="Cleanup Expired Sessions",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"Scheduler started with daily update at {format_update_times(update_times)}")


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    if schedule.scheduler.running:
        schedule.scheduler.shutdown(wait=True)
        logger.info("Scheduler shutdown complete")
