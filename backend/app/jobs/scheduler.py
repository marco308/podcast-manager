"""APScheduler setup and job management."""

import contextlib
import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_maker
from app.jobs import locks
from app.jobs.session_cleanup import cleanup_expired_sessions as _cleanup_expired_sessions
from app.models.playlist import Playlist
from app.models.settings import AppSetting
from app.models.sync_log import SyncLog, SyncStatus
from app.models.user import User
from app.services.playlist_builder import PlaylistBuilder
from app.services.spotify import CleanupBudgetExceeded, SpotifyService
from app.services.token_manager import TokenManager

# How recently a successful playlist_update must have run for cleanup
# to defer to it (issue #89, PR3). Stops the cleanup job from starving
# the daily rebuild when both want the write lock.
CLEANUP_RECENCY_WINDOW = timedelta(minutes=60)

# Per-run cap on Spotify API calls for the cleanup job (issue #89, PR2).
# Keeps a misbehaving run from burning through the user's rate-limit
# budget and starving the daily rebuild.
CLEANUP_API_CALL_BUDGET = 200

# AppSetting key for the cleanup rotation cursor (issue #182): when a run
# exhausts its budget, the next run starts at the first deferred playlist
# instead of re-cleaning the same head of the list every time.
CLEANUP_ROTATION_KEY = "cleanup_rotation_offset"

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

logger = logging.getLogger(__name__)
settings = get_settings()

# Global scheduler instance
scheduler = AsyncIOScheduler()

# Track last run times in-memory for interval jobs
_last_run_times: dict[str, datetime] = {}


# Jobs whose runs are recorded in SyncLog, keyed by scheduler job id. Their
# last run is read from the table so it survives a restart; the in-memory
# _last_run_times only covers the current process (issue #248).
_SYNCLOG_JOB_TYPES: dict[str, str] = {
    "daily_playlist_update": "playlist_update",
    "remove_played_episodes": "cleanup",
}


def _record_run(job_id: str) -> None:
    """Record the current time as the last run for a job."""
    _last_run_times[job_id] = datetime.now(UTC)


async def _upsert_app_setting(db, key: str, value: str) -> None:
    """Insert or update a single ``app_settings`` row. The caller commits."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(AppSetting(key=key, value=value))


async def cleanup_expired_sessions() -> None:
    """Wrapper around session cleanup that records run time."""
    _record_run("session_cleanup")
    await _cleanup_expired_sessions()


async def refresh_all_tokens() -> None:
    """Refresh Spotify tokens for all users before they expire.

    Delegates the refresh to :class:`TokenManager` so it happens under the
    per-user lock, with the refresh token re-read inside it — a snapshot
    taken outside the lock can race a concurrent TokenManager refresh and
    persist a superseded (rotated) refresh token, which Spotify then
    rejects with ``invalid_grant`` (issue #167).
    """
    _record_run("token_refresh")
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


async def update_all_playlists() -> None:
    """Update all enabled playlists for all users.

    Uses a separate DB session per user so that Spotify API calls for one user
    don't hold a write lock that blocks the rest of the application.
    """
    _record_run("daily_playlist_update")
    logger.info("Starting daily playlist update job")

    # Create sync log with a short-lived session
    sync_log_id: int | None = None
    try:
        async with async_session_maker() as db:
            sync_log = SyncLog(
                job_type="playlist_update",
                status=SyncStatus.RUNNING,
                started_at=datetime.now(UTC),
            )
            db.add(sync_log)
            await db.commit()
            sync_log_id = sync_log.id
    except Exception as e:
        logger.error(f"Playlist update job failed creating sync log: {e}")

    # Read user IDs with a short-lived session
    user_ids: list[int] = []
    read_error: str | None = None
    try:
        async with async_session_maker() as db:
            result = await db.execute(select(User.id))
            user_ids = [row[0] for row in result.all()]
    except Exception as e:
        logger.error(f"Playlist update job failed reading users: {e}")
        read_error = str(e)

    if read_error is not None:
        # Don't leave the RUNNING row created above orphaned (issue #174).
        await _finalise_playlist_update_log(
            sync_log_id,
            status=SyncStatus.FAILED,
            details=f"Failed reading users: {read_error}",
            failure_code="unknown",
        )
        return

    total_playlists = 0
    total_episodes = 0
    playlists_failed = 0
    playlists_skipped = 0
    errors: list[str] = []
    error_objects: list[BaseException] = []

    try:
        # Serialise against cleanup and any concurrent manual run (issue #89, PR3).
        if locks.playlist_write_lock.locked():
            logger.info("Waiting on playlist_write_lock — another job is holding it")
        async with locks.playlist_write_lock:
            # Process each user with its own session
            for user_id in user_ids:
                async with async_session_maker() as db:
                    try:
                        result = await db.execute(select(User).where(User.id == user_id))
                        user = result.scalar_one_or_none()

                        if not user:
                            continue

                        token_manager = TokenManager(user.id)
                        builder = PlaylistBuilder(db, user, token_manager=token_manager)
                        results = await builder.update_all_playlists()

                        for res in results:
                            if res.skipped:
                                # Weekend-only playlist on a non-qualifying day —
                                # deliberately untouched, so don't count it as an
                                # attempted rebuild (issue #150).
                                playlists_skipped += 1
                                continue
                            total_playlists += 1
                            if res.success:
                                total_episodes += res.episode_count
                            else:
                                playlists_failed += 1
                                errors.append(f"{res.playlist_name}: {res.error}")

                        await db.commit()

                    except Exception as e:
                        logger.error(f"Failed to update playlists for user {user_id}: {e}")
                        errors.append(f"User {user_id}: {str(e)}")
                        error_objects.append(e)
                        await db.rollback()
    except Exception as e:
        # The per-user try above is the intended last line of defence; if
        # something still escapes it, the RUNNING SyncLog row must not be
        # orphaned (issue #174).
        logger.error(f"Playlist update job failed unexpectedly: {e}")
        errors.append(str(e))
        error_objects.append(e)

    details = f"Updated {total_playlists} playlists with {total_episodes} episodes. Errors: {len(errors)}"
    if playlists_skipped:
        details += f" Skipped (weekend-only): {playlists_skipped}."
    if errors:
        details += f"\n{chr(10).join(errors[:10])}"

    await _finalise_playlist_update_log(
        sync_log_id,
        status=SyncStatus.SUCCESS if not errors else SyncStatus.FAILED,
        details=details,
        # Failure classification (issue #89, PR1).
        failure_code=_classify_failure(
            playlists_attempted=total_playlists,
            playlists_failed=playlists_failed,
            error_messages=errors,
            exceptions=error_objects,
        ),
        playlists_attempted=total_playlists,
        playlists_failed=playlists_failed,
    )

    logger.info(
        f"Playlist update job completed: {total_playlists} playlists, {total_episodes} episodes, "
        f"{len(errors)} errors, {playlists_skipped} skipped"
    )


async def _finalise_playlist_update_log(
    sync_log_id: int | None,
    *,
    status: SyncStatus,
    details: str,
    failure_code: str | None,
    playlists_attempted: int = 0,
    playlists_failed: int = 0,
) -> None:
    """Update the playlist-update SyncLog row with the final outcome."""
    if sync_log_id is None:
        return
    async with async_session_maker() as db:
        try:
            result = await db.execute(select(SyncLog).where(SyncLog.id == sync_log_id))
            sync_log = result.scalar_one_or_none()
            if sync_log:
                sync_log.status = status
                sync_log.completed_at = datetime.now(UTC)
                sync_log.details = details
                sync_log.failure_code = failure_code
                sync_log.playlists_attempted = playlists_attempted
                sync_log.playlists_failed = playlists_failed
                # api_calls_used left None — budget tracking lands in PR2.
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to update sync log: {e}")


# failure_code written by the startup sweep below. Distinct from the codes
# _classify_failure produces so the history can tell "the job broke" apart
# from "the process went away underneath the job".
INTERRUPTED_FAILURE_CODE = "interrupted"


async def fail_orphaned_sync_logs() -> int:
    """Close out SyncLog rows left ``RUNNING`` by a previous process.

    Every job writes a ``RUNNING`` row before it starts and finalises it on
    the way out (issue #174). That covers every exit path *inside* the
    process — but not the process itself dying mid-run (deploy, OOM, host
    reboot). Those rows stayed ``RUNNING`` forever, and because
    ``get_job_status`` reports ``last_run`` from ``started_at`` regardless of
    status, the UI showed the interrupted run as a recent, successful-looking
    one (issue #161).

    The jobs run in-process under APScheduler, so at scheduler start nothing
    can legitimately be running: any ``RUNNING`` row is an orphan by
    construction. No heartbeat or staleness window is needed — a startup
    sweep is exact. Called from :func:`init_scheduler`; a failure here is
    logged and never blocks startup.

    Returns:
        Number of rows marked ``FAILED``.
    """
    async with async_session_maker() as db:
        result = await db.execute(select(SyncLog).where(SyncLog.status == SyncStatus.RUNNING))
        orphans = list(result.scalars().all())
        if not orphans:
            return 0
        now = datetime.now(UTC)
        for row in orphans:
            row.status = SyncStatus.FAILED
            row.completed_at = now
            row.failure_code = INTERRUPTED_FAILURE_CODE
            row.details = "Interrupted: the process stopped before this run finished (marked failed at startup)."
        await db.commit()
    logger.warning(f"Marked {len(orphans)} interrupted SyncLog run(s) as failed at startup")
    return len(orphans)


async def init_scheduler() -> None:
    """Initialize and start the scheduler with configured jobs."""
    if scheduler.running:
        return

    # Nothing can be running yet, so any RUNNING row is left over from a
    # process that died mid-job. Close it out before the jobs (and the UI's
    # last-run lookup) can see it.
    try:
        await fail_orphaned_sync_logs()
    except Exception as e:
        logger.error(f"Failed to sweep orphaned SyncLog rows at startup: {e}")

    # Read persisted schedule from DB
    update_hour = settings.PLAYLIST_UPDATE_HOUR
    update_minute = settings.PLAYLIST_UPDATE_MINUTE
    try:
        async with async_session_maker() as db:
            result = await db.execute(select(AppSetting).where(AppSetting.key == "playlist_update_hour"))
            hour_setting = result.scalar_one_or_none()
            if hour_setting:
                update_hour = int(hour_setting.value)

            result = await db.execute(select(AppSetting).where(AppSetting.key == "playlist_update_minute"))
            minute_setting = result.scalar_one_or_none()
            if minute_setting:
                update_minute = int(minute_setting.value)
    except Exception as e:
        logger.warning(f"Failed to read persisted schedule, using defaults: {e}")

    # Daily playlist update job
    scheduler.add_job(
        update_all_playlists,
        CronTrigger(hour=update_hour, minute=update_minute),
        id="daily_playlist_update",
        name="Daily Playlist Update",
        replace_existing=True,
    )

    # Token refresh — the threshold in refresh_all_tokens must stay above
    # this interval (issue #166), see TOKEN_REFRESH_THRESHOLD_SECONDS.
    scheduler.add_job(
        refresh_all_tokens,
        IntervalTrigger(minutes=TOKEN_REFRESH_INTERVAL_MINUTES),
        id="token_refresh",
        name="Spotify Token Refresh",
        replace_existing=True,
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
    logger.info(f"Scheduler started with daily update at {update_hour:02d}:{update_minute:02d}")


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler shutdown complete")


async def get_job_status() -> list[dict]:
    """Get status of all scheduled jobs with enhanced info."""
    jobs = scheduler.get_jobs()

    # Last run of each SyncLog-backed job, read from the table so it survives
    # a restart. The status travels with the timestamp so a failed or
    # interrupted run isn't shown as if it worked (issue #161).
    synclog_last_runs: dict[str, tuple[datetime, str]] = {}
    try:
        async with async_session_maker() as db:
            for job_type in set(_SYNCLOG_JOB_TYPES.values()):
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
        if isinstance(job.trigger, CronTrigger):
            info["type"] = "cron"
            # Extract hour/minute from cron trigger fields
            hour = settings.PLAYLIST_UPDATE_HOUR
            minute = settings.PLAYLIST_UPDATE_MINUTE
            # Try to get from the actual trigger
            for field in job.trigger.fields:
                if field.name == "hour":
                    with contextlib.suppress(ValueError, TypeError):
                        hour = int(str(field))
                elif field.name == "minute":
                    with contextlib.suppress(ValueError, TypeError):
                        minute = int(str(field))
            info["schedule"] = {"hour": hour, "minute": minute}
            info["is_configurable"] = job.id == "daily_playlist_update"
        elif isinstance(job.trigger, IntervalTrigger):
            info["type"] = "interval"
            # Get interval in minutes
            interval_seconds = job.trigger.interval.total_seconds()
            info["interval_minutes"] = int(interval_seconds / 60)

        # UTCDateTime and _record_run both yield aware datetimes, so
        # isoformat() already carries the offset — no manual "Z" (issue #156).
        # SyncLog is the only source for the jobs that write it: _record_run
        # fires before the row exists (the cleanup recency gate returns before
        # writing one at all), so falling back to the in-memory time would
        # report a run that did no work and carry no status.
        job_type = _SYNCLOG_JOB_TYPES.get(job.id)
        if job_type is not None:
            synclog_run = synclog_last_runs.get(job_type)
            if synclog_run:
                info["last_run"] = synclog_run[0].isoformat()
                info["last_run_status"] = synclog_run[1]
        else:
            in_memory_run = _last_run_times.get(job.id)
            info["last_run"] = in_memory_run.isoformat() if in_memory_run else None

        result.append(info)

    return result


async def reschedule_playlist_update(hour: int, minute: int) -> str | None:
    """Reschedule the daily playlist update and persist the new time.

    Returns:
        The next run time as an ISO string, or None if the job has no next
        run (i.e. it is paused). Failures raise rather than returning None —
        the exception carries the reason and is already logged (issue #159).

    Raises:
        Exception: propagated from APScheduler or the settings write.
    """
    try:
        # Persist first, reschedule after: applying the trigger before the
        # write meant a failed write left the live schedule diverging from
        # the persisted one until the next restart (issue #182).
        async with async_session_maker() as db:
            for key, value in [("playlist_update_hour", str(hour)), ("playlist_update_minute", str(minute))]:
                await _upsert_app_setting(db, key, value)
            await db.commit()

        scheduler.reschedule_job(
            "daily_playlist_update",
            trigger=CronTrigger(hour=hour, minute=minute),
        )

        # Get updated next run time
        job = scheduler.get_job("daily_playlist_update")
        next_run = job.next_run_time.isoformat() if job and job.next_run_time else None

        logger.info(f"Rescheduled daily playlist update to {hour:02d}:{minute:02d}, next run: {next_run}")
        return next_run
    except Exception as e:
        logger.error(f"Failed to reschedule daily playlist update: {e}")
        raise


def _classify_failure(
    *,
    playlists_attempted: int,
    playlists_failed: int,
    error_messages: list[str],
    exceptions: list[BaseException],
) -> str | None:
    """Classify the failure mode of a playlist-update job for SyncLog.

    The classification is heuristic — we don't carry structured error
    objects around the job today. We inspect both raised exceptions
    (typically httpx.HTTPStatusError from user-level failures) and the
    error message strings produced by ``update_playlist`` to recognise
    well-known patterns.

    Returns:
        One of: rate_limit, token_expired, playlist_write_failed,
        partial, unknown — or None if there were no failures.
    """
    import httpx  # local import to avoid cycles in tests that stub modules

    if not error_messages and not exceptions:
        return None

    statuses: list[int] = []
    methods: list[str] = []
    for exc in exceptions:
        if isinstance(exc, httpx.HTTPStatusError):
            statuses.append(exc.response.status_code)
            methods.append(exc.request.method.upper())

    # Also peek into the textual errors — update_playlist wraps the
    # underlying exception via str(e), which for httpx prints the status.
    text_blob = " ".join(error_messages)

    if 429 in statuses or "429" in text_blob or "Too Many Requests" in text_blob:
        return "rate_limit"
    if 401 in statuses or "401" in text_blob or "Unauthorized" in text_blob:
        return "token_expired"

    write_methods = {"PUT", "POST", "DELETE"}
    for status, method in zip(statuses, methods, strict=False):
        if method in write_methods and 400 <= status < 600:
            return "playlist_write_failed"

    if playlists_failed and playlists_failed < playlists_attempted:
        return "partial"

    return "unknown"


async def _still_enabled_playlist_ids() -> set[int] | None:
    """Playlist IDs that are still enabled, re-read at the write boundary.

    Cleanup reads its playlists before it takes ``playlist_write_lock``, and
    ``PATCH /playlists/{id}`` doesn't take that lock — so a playlist disabled
    while cleanup queued would otherwise still be written to, and a disabled
    playlist is never written to (issue #239).

    Returns ``None`` if the re-read itself failed: cleanup then falls back to
    the earlier read rather than skipping every playlist.
    """
    try:
        async with async_session_maker() as db:
            # Same query shape as the phase-1 read, minus the user filter.
            result = await db.execute(select(Playlist).where(Playlist.is_enabled.is_(True)))
            return {p.id for p in result.scalars().all()}
    except Exception as e:
        logger.error(f"Cleanup could not re-check is_enabled (using the earlier read): {e}")
        return None


def _played_uris_from_items(items: list[dict]) -> list[str]:
    """Extract URIs of fully-played episodes from a playlist-items page.

    Relies on the ``fields`` mask in :meth:`SpotifyService.get_playlist_tracks`
    which requests ``resume_point(fully_played)`` — so no second
    per-episode round-trip is needed (issue #89, PR2).
    """
    played: list[str] = []
    for item in items:
        if not item:
            continue
        track = item.get("track")
        if not track:
            continue
        uri = track.get("uri")
        if not uri or not uri.startswith("spotify:episode:"):
            continue
        resume_point = track.get("resume_point") or {}
        if resume_point.get("fully_played"):
            played.append(uri)
    return played


async def remove_played_episodes_from_playlists() -> None:
    """Remove fully-played episodes from all playlists for all users.

    Runs every 30 minutes (issue #89, PR2). Filters played episodes
    directly from the playlist-items pages (the ``fields`` mask already
    pulls ``resume_point.fully_played``), so no per-episode follow-up
    fetch — that fan-out is what was burning the rate limit.

    Each cleanup run gets a budget of :data:`CLEANUP_API_CALL_BUDGET`
    Spotify calls, enforced both between playlists and between pagination
    pages of a single playlist — a playlist whose paging runs the budget
    dry is deferred whole rather than half-cleaned (issue #182). If
    Spotify replies with a long Retry-After the SpotifyService raises
    ``CleanupBudgetExceeded`` and we finalise the run with a SyncLog row
    rather than blocking the daily rebuild.

    Any run that doesn't reach every playlist persists a rotation cursor
    (:data:`CLEANUP_ROTATION_KEY`) so the next one starts on the first
    playlist it missed instead of re-cleaning the same head of the list
    and starving the tail (issue #182).
    """
    _record_run("remove_played_episodes")
    logger.info("Starting remove played episodes job")

    # Recency gate (issue #89, PR3): if a rebuild completed successfully
    # in the last 60 minutes, the playlists are already fresh — there's
    # nothing for cleanup to do, and skipping early means we don't
    # contend for the write lock against a still-running rebuild on a
    # tight schedule.
    recent = None
    try:
        async with async_session_maker() as db:
            cutoff = datetime.now(UTC) - CLEANUP_RECENCY_WINDOW
            recent_result = await db.execute(
                select(SyncLog)
                .where(
                    (SyncLog.job_type == "playlist_update")
                    & (SyncLog.status == SyncStatus.SUCCESS)
                    & (SyncLog.completed_at > cutoff)
                )
                .order_by(SyncLog.completed_at.desc())
                .limit(1)
            )
            recent = recent_result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Cleanup recency check failed (continuing anyway): {e}")
        recent = None

    if recent is not None:
        logger.info(f"Skipping cleanup — successful playlist_update at {recent.completed_at} (<60min ago)")
        return

    # Create the SyncLog row up front so partial failures still leave a trace.
    sync_log_id: int | None = None
    try:
        async with async_session_maker() as db:
            sync_log = SyncLog(
                job_type="cleanup",
                status=SyncStatus.RUNNING,
                started_at=datetime.now(UTC),
            )
            db.add(sync_log)
            await db.commit()
            sync_log_id = sync_log.id
    except Exception as e:
        logger.error(f"Cleanup job failed creating sync log: {e}")

    # Phase 1: Read users, playlists and the rotation cursor with a
    # short-lived session
    rotation_offset = 0
    user_playlists: list[tuple[int, list[tuple[int, str, str]]]] = []  # [(user_id, [(playlist_id, name, spotify_id)])]
    read_error: str | None = None
    try:
        async with async_session_maker() as db:
            offset_result = await db.execute(select(AppSetting).where(AppSetting.key == CLEANUP_ROTATION_KEY))
            offset_setting = offset_result.scalar_one_or_none()
            if offset_setting:
                with contextlib.suppress(ValueError, TypeError):
                    rotation_offset = int(offset_setting.value)

            result = await db.execute(select(User))
            users = result.scalars().all()

            for user in users:
                # Disabled playlists are never written to, cleanup included
                # (issue #239) — they keep whatever they had until re-enabled.
                # Re-checked under the write lock in phase 2, since this read
                # happens before the lock is taken.
                playlists_result = await db.execute(
                    select(Playlist).where((Playlist.user_id == user.id) & (Playlist.is_enabled == True))
                )
                playlists = playlists_result.scalars().all()

                playlist_info = [(p.id, p.name, p.spotify_playlist_id) for p in playlists if p.spotify_playlist_id]
                if playlist_info:
                    if rotation_offset:
                        # Start where the previous incomplete run stopped
                        # (issue #182).
                        k = rotation_offset % len(playlist_info)
                        playlist_info = playlist_info[k:] + playlist_info[:k]
                    user_playlists.append((user.id, playlist_info))
    except Exception as e:
        logger.error(f"Remove played episodes job failed reading DB: {e}")
        read_error = str(e)

    if read_error is not None:
        await _finalise_cleanup_log(
            sync_log_id,
            status=SyncStatus.FAILED,
            details=f"Failed reading users/playlists: {read_error}",
            failure_code="unknown",
            playlists_attempted=0,
            playlists_failed=0,
            api_calls_used=0,
        )
        return

    # Phase 2: Process each playlist
    playlists_attempted = 0
    # Rotation bookkeeping, deliberately distinct from playlists_attempted:
    # a playlist cut off mid-pagination doesn't count as *attempted* (its
    # read was incomplete — issue #161) but it does count as *consumed*, so
    # the cursor steps over it. Otherwise one pathological playlist that
    # can never fit in a single budget would pin the cursor at its index
    # and starve everything behind it forever (issue #182).
    playlists_consumed = 0
    playlists_failed = 0
    total_removed = 0
    api_calls_used = 0
    errors: list[str] = []
    error_objects: list[BaseException] = []
    aborted_for_rate_limit = False

    try:
        # Serialise against rebuild and any concurrent manual run (issue #89, PR3).
        if locks.playlist_write_lock.locked():
            logger.info("Waiting on playlist_write_lock — another job is holding it")
        async with locks.playlist_write_lock:
            # Phase 1 read is_enabled without the lock; re-check it now that
            # we hold it (issue #239). Dropping the rows here rather than
            # inside the loop keeps the rotation bookkeeping counting the
            # list it actually walks — the cursor is best-effort anyway, and
            # the next run rebuilds the list from scratch.
            still_enabled = await _still_enabled_playlist_ids()
            if still_enabled is not None:
                user_playlists = [
                    (user_id, kept)
                    for user_id, playlists in user_playlists
                    # A user left with nothing drops out, as in phase 1 — no
                    # point fetching a token and opening a client for them.
                    if (kept := [p for p in playlists if p[0] in still_enabled])
                ]

            for user_id, playlists in user_playlists:
                if aborted_for_rate_limit:
                    break
                token_manager = TokenManager(user_id)
                try:
                    access_token = await token_manager.get_token(min_remaining_seconds=300)
                except RuntimeError:
                    logger.warning(f"User {user_id} not found, skipping")
                    continue
                except Exception as e:
                    # TokenDecryptionError / network failures must not escape
                    # past the SyncLog finalisation below (issue #174).
                    logger.error(f"Failed to get token for user {user_id}: {e}")
                    errors.append(f"User {user_id}: {str(e)}")
                    error_objects.append(e)
                    continue

                spotify_client = SpotifyService(access_token=access_token)
                spotify_client.reset_api_counter()

                try:
                    # Reuse one httpx client for the whole user (issue #182) —
                    # per-call clients were opening a fresh connection for
                    # every pagination request.
                    async with spotify_client:
                        for _playlist_id, playlist_name, spotify_playlist_id in playlists:
                            # Per-run API budget — give up early if we've already
                            # spent the allowance; the rotation cursor persisted
                            # below starts the next run at the first deferred
                            # playlist. Checked before counting the playlist as
                            # attempted, so a deferred playlist isn't reported
                            # as one we tried (issue #161).
                            if spotify_client.api_calls_used >= CLEANUP_API_CALL_BUDGET:
                                logger.warning(
                                    f"Cleanup API budget ({CLEANUP_API_CALL_BUDGET}) exhausted; "
                                    f"deferring remaining playlists to next run"
                                )
                                break

                            playlists_attempted += 1
                            playlists_consumed += 1

                            try:
                                # Walk playlist-items pages, filtering inline.
                                offset = 0
                                limit = 50
                                played_uris: list[str] = []
                                collection_deferred = False

                                while True:
                                    # The budget can also run dry mid-pagination on
                                    # a large playlist (issue #182): stop collecting
                                    # and skip this playlist's deletions — it is
                                    # deferred whole to the next run.
                                    if spotify_client.api_calls_used >= CLEANUP_API_CALL_BUDGET:
                                        collection_deferred = True
                                        break

                                    tracks_data = await spotify_client.get_playlist_tracks(
                                        spotify_playlist_id,
                                        limit=limit,
                                        offset=offset,
                                        cleanup_mode=True,
                                    )
                                    items = tracks_data.get("items", [])
                                    if not items:
                                        break

                                    played_uris.extend(_played_uris_from_items(items))

                                    offset += limit
                                    if not tracks_data.get("next"):
                                        break

                                if collection_deferred:
                                    # Deferred, not attempted (issue #161).
                                    # playlists_consumed keeps the increment so
                                    # the cursor steps past it next run.
                                    playlists_attempted -= 1
                                    logger.warning(
                                        f"Cleanup API budget ({CLEANUP_API_CALL_BUDGET}) exhausted "
                                        f"mid-pagination in playlist {playlist_name}; deferring to next run"
                                    )
                                    break

                                if played_uris:
                                    logger.info(
                                        f"Playlist {playlist_name} ({spotify_playlist_id}) - "
                                        f"found {len(played_uris)} fully-played episodes"
                                    )
                                    for i in range(0, len(played_uris), 50):
                                        batch = played_uris[i : i + 50]
                                        try:
                                            # Refresh at the write boundary (PR1 wiring).
                                            spotify_client._access_token = await token_manager.get_token(
                                                min_remaining_seconds=300
                                            )
                                            await spotify_client.remove_tracks_from_playlist(
                                                spotify_playlist_id,
                                                batch,
                                                on_unauthorized=token_manager.force_refresh,
                                                cleanup_mode=True,
                                            )
                                            total_removed += len(batch)
                                            logger.info(
                                                f"Removed {len(batch)} played episodes from "
                                                f"playlist {playlist_name} (user {user_id})"
                                            )
                                        except CleanupBudgetExceeded:
                                            raise
                                        except Exception as e:
                                            logger.error(
                                                f"Failed to remove batch from playlist {playlist_name} "
                                                f"(user {user_id}): {e} - batch: {batch}"
                                            )
                                            playlists_failed += 1
                                            errors.append(f"Playlist {playlist_name}: {str(e)}")
                                            error_objects.append(e)
                                            break  # stop further batches for this playlist

                            except CleanupBudgetExceeded:
                                raise
                            except Exception as e:
                                logger.error(f"Failed to clean playlist {playlist_name} (user {user_id}): {e}")
                                playlists_failed += 1
                                errors.append(f"Playlist {playlist_name}: {str(e)}")
                                error_objects.append(e)

                except CleanupBudgetExceeded:
                    logger.warning("cleanup aborted: Spotify rate-limit Retry-After > 60s")
                    aborted_for_rate_limit = True
                except Exception as e:
                    logger.error(f"Failed to clean playlists for user {user_id}: {e}")
                    errors.append(f"User {user_id}: {str(e)}")
                    error_objects.append(e)
                finally:
                    api_calls_used += spotify_client.api_calls_used
    except Exception as e:
        # The per-user try above is the intended last line of defence; if
        # something still escapes it, the RUNNING SyncLog row must not be
        # orphaned (issue #174).
        logger.error(f"Cleanup job failed unexpectedly: {e}")
        errors.append(str(e))
        error_objects.append(e)

    # Finalise the SyncLog row. This happens before the rotation-cursor
    # write below: closing out the RUNNING row is the obligation (issue
    # #174), the cursor is best-effort bookkeeping.
    if aborted_for_rate_limit:
        status = SyncStatus.FAILED
        failure_code = "rate_limit"
        details = (
            f"cleanup aborted: Spotify rate-limit Retry-After > 60s. Removed {total_removed} episodes before abort."
        )
    elif errors:
        status = SyncStatus.FAILED
        failure_code = _classify_failure(
            playlists_attempted=playlists_attempted,
            playlists_failed=playlists_failed,
            error_messages=errors,
            exceptions=error_objects,
        )
        details = f"Removed {total_removed} episodes across {playlists_attempted} playlists. Errors: {len(errors)}"
        if errors:
            details += f"\n{chr(10).join(errors[:10])}"
    else:
        status = SyncStatus.SUCCESS
        failure_code = None
        details = f"Removed {total_removed} episodes across {playlists_attempted} playlists."

    await _finalise_cleanup_log(
        sync_log_id,
        status=status,
        details=details,
        failure_code=failure_code,
        playlists_attempted=playlists_attempted,
        playlists_failed=playlists_failed,
        api_calls_used=api_calls_used,
    )

    # Rotation cursor (issue #182). A run that didn't get through every
    # available playlist — budget exhausted, rate-limit abort, or an
    # unexpected error — advances the cursor by what it did consume, so
    # the next run starts on the first playlist this one never reached
    # rather than re-cleaning the same head of the list forever and
    # starving the tail. A run that covered everything resets the cursor.
    # Single-user by construction (see CLAUDE.md), so one cursor over the
    # concatenated per-user lists is exact.
    total_available = sum(len(pls) for _, pls in user_playlists)
    if total_available and playlists_consumed < total_available:
        new_offset = (rotation_offset + playlists_consumed) % total_available
    else:
        new_offset = 0
    if new_offset != rotation_offset:
        await _persist_cleanup_rotation_offset(new_offset)

    logger.info(
        f"Remove played episodes job completed: removed {total_removed} episodes, "
        f"{len(errors)} errors, {api_calls_used} API calls used"
    )


async def _persist_cleanup_rotation_offset(offset: int) -> None:
    """Store the cleanup rotation cursor (issue #182).

    Best-effort: losing the cursor costs one repeated head-of-list pass,
    not correctness — and a write failure here must never stop the caller
    from finalising its RUNNING SyncLog row (issue #174), so everything is
    swallowed and logged.
    """
    try:
        async with async_session_maker() as db:
            await _upsert_app_setting(db, CLEANUP_ROTATION_KEY, str(offset))
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to persist cleanup rotation cursor: {e}")


async def _finalise_cleanup_log(
    sync_log_id: int | None,
    *,
    status: SyncStatus,
    details: str,
    failure_code: str | None,
    playlists_attempted: int,
    playlists_failed: int,
    api_calls_used: int,
) -> None:
    """Update the cleanup SyncLog row with the final outcome."""
    if sync_log_id is None:
        return
    async with async_session_maker() as db:
        try:
            result = await db.execute(select(SyncLog).where(SyncLog.id == sync_log_id))
            sync_log = result.scalar_one_or_none()
            if sync_log:
                sync_log.status = status
                sync_log.completed_at = datetime.now(UTC)
                sync_log.details = details
                sync_log.failure_code = failure_code
                sync_log.playlists_attempted = playlists_attempted
                sync_log.playlists_failed = playlists_failed
                sync_log.api_calls_used = api_calls_used
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to update cleanup sync log: {e}")
