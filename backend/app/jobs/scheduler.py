"""APScheduler setup and job management."""

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_maker
from app.jobs.session_cleanup import cleanup_expired_sessions as _cleanup_expired_sessions
from app.models.playlist import Playlist
from app.models.settings import AppSetting
from app.models.sync_log import SyncLog, SyncStatus
from app.models.user import User
from app.services.encryption import get_encryption_service
from app.services.playlist_builder import PlaylistBuilder
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)
settings = get_settings()

# Global scheduler instance
scheduler = AsyncIOScheduler()

# Track last run times in-memory for interval jobs
_last_run_times: dict[str, datetime] = {}


def _record_run(job_id: str) -> None:
    """Record the current time as the last run for a job."""
    _last_run_times[job_id] = datetime.now(UTC)


async def cleanup_expired_sessions() -> None:
    """Wrapper around session cleanup that records run time."""
    _record_run("session_cleanup")
    await _cleanup_expired_sessions()


async def refresh_all_tokens() -> None:
    """Refresh Spotify tokens for all users before they expire.

    Uses short-lived DB sessions — one per user — to avoid holding write locks
    during Spotify API calls.
    """
    _record_run("token_refresh")
    logger.info("Starting token refresh job")

    encryption = get_encryption_service()

    # Phase 1: Read users needing refresh with a short-lived session
    users_to_refresh: list[tuple[int, str, str]] = []  # [(user_id, display_name, encrypted_refresh_token)]
    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User))
            users = result.scalars().all()

            for user in users:
                token_exp = user.token_expires_at.replace(tzinfo=UTC) if user.token_expires_at.tzinfo is None else user.token_expires_at
                if (token_exp.timestamp() - datetime.now(UTC).timestamp()) < 900:
                    users_to_refresh.append((user.id, user.display_name, user.refresh_token))
        except Exception as e:
            logger.error(f"Token refresh job failed reading DB: {e}")
            return

    # Phase 2: Refresh each user's token with Spotify API, then write back
    for user_id, display_name, encrypted_refresh_token in users_to_refresh:
        try:
            refresh_token = encryption.decrypt(encrypted_refresh_token)
            spotify = SpotifyService()
            token_data = await spotify.refresh_access_token(refresh_token)

            # Short-lived session to write updated tokens
            async with async_session_maker() as db:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user:
                    user.access_token = encryption.encrypt(token_data["access_token"])
                    user.refresh_token = encryption.encrypt(token_data["refresh_token"])
                    user.token_expires_at = token_data["expires_at"]
                    await db.commit()
                    logger.info(f"Refreshed token for user {display_name}")

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
    async with async_session_maker() as db:
        try:
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
    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User.id))
            user_ids = [row[0] for row in result.all()]
        except Exception as e:
            logger.error(f"Playlist update job failed reading users: {e}")
            return

    total_playlists = 0
    total_episodes = 0
    errors = []

    # Process each user with its own session
    for user_id in user_ids:
        async with async_session_maker() as db:
            try:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()

                if not user:
                    continue

                builder = PlaylistBuilder(db, user)
                results = await builder.update_all_playlists()

                for res in results:
                    total_playlists += 1
                    if res.success:
                        total_episodes += res.episode_count
                    else:
                        errors.append(f"{res.playlist_name}: {res.error}")

                await db.commit()

            except Exception as e:
                logger.error(f"Failed to update playlists for user {user_id}: {e}")
                errors.append(f"User {user_id}: {str(e)}")
                await db.rollback()

    # Update sync log with a short-lived session
    if sync_log_id:
        async with async_session_maker() as db:
            try:
                result = await db.execute(select(SyncLog).where(SyncLog.id == sync_log_id))
                sync_log = result.scalar_one_or_none()
                if sync_log:
                    sync_log.status = SyncStatus.SUCCESS if not errors else SyncStatus.FAILED
                    sync_log.completed_at = datetime.now(UTC)
                    sync_log.details = (
                        f"Updated {total_playlists} playlists with {total_episodes} episodes. Errors: {len(errors)}"
                    )
                    if errors:
                        sync_log.details += f"\n{chr(10).join(errors[:10])}"
                    await db.commit()
            except Exception as e:
                logger.error(f"Failed to update sync log: {e}")

    logger.info(
        f"Playlist update job completed: {total_playlists} playlists, "
        f"{total_episodes} episodes, {len(errors)} errors"
    )


async def init_scheduler() -> None:
    """Initialize and start the scheduler with configured jobs."""
    if scheduler.running:
        return

    # Read persisted schedule from DB
    update_hour = settings.PLAYLIST_UPDATE_HOUR
    update_minute = settings.PLAYLIST_UPDATE_MINUTE
    try:
        async with async_session_maker() as db:
            result = await db.execute(
                select(AppSetting).where(AppSetting.key == "playlist_update_hour")
            )
            hour_setting = result.scalar_one_or_none()
            if hour_setting:
                update_hour = int(hour_setting.value)

            result = await db.execute(
                select(AppSetting).where(AppSetting.key == "playlist_update_minute")
            )
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

    # Token refresh every 45 minutes
    scheduler.add_job(
        refresh_all_tokens,
        IntervalTrigger(minutes=45),
        id="token_refresh",
        name="Spotify Token Refresh",
        replace_existing=True,
    )

    # Remove played episodes every 5 minutes
    # NOTE: 5-minute interval is aggressive given per-episode API fetches.
    # Consider increasing to 15-30 minutes if rate-limiting becomes an issue.
    scheduler.add_job(
        remove_played_episodes_from_playlists,
        IntervalTrigger(minutes=5),
        id="remove_played_episodes",
        name="Remove Played Episodes",
        replace_existing=True,
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
    logger.info(
        f"Scheduler started with daily update at "
        f"{update_hour:02d}:{update_minute:02d}"
    )


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler shutdown complete")


async def get_job_status() -> list[dict]:
    """Get status of all scheduled jobs with enhanced info."""
    jobs = scheduler.get_jobs()

    # Get last playlist_update run from SyncLog
    playlist_last_run = None
    try:
        async with async_session_maker() as db:
            result = await db.execute(
                select(SyncLog)
                .where(SyncLog.job_type == "playlist_update")
                .order_by(SyncLog.started_at.desc())
                .limit(1)
            )
            last_sync = result.scalar_one_or_none()
            if last_sync and last_sync.started_at:
                if last_sync.started_at.tzinfo is None:
                    playlist_last_run = last_sync.started_at.isoformat() + "Z"
                else:
                    playlist_last_run = last_sync.started_at.isoformat()
    except Exception:
        pass

    result = []
    for job in jobs:
        info: dict = {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "last_run": None,
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
                    try:
                        hour = int(str(field))
                    except (ValueError, TypeError):
                        pass
                elif field.name == "minute":
                    try:
                        minute = int(str(field))
                    except (ValueError, TypeError):
                        pass
            info["schedule"] = {"hour": hour, "minute": minute}
            info["is_configurable"] = job.id == "daily_playlist_update"
            if job.id == "daily_playlist_update":
                info["last_run"] = playlist_last_run
        elif isinstance(job.trigger, IntervalTrigger):
            info["type"] = "interval"
            # Get interval in minutes
            interval_seconds = job.trigger.interval.total_seconds()
            info["interval_minutes"] = int(interval_seconds / 60)
            info["last_run"] = _last_run_times.get(job.id, None)
            if info["last_run"] and isinstance(info["last_run"], datetime):
                if info["last_run"].tzinfo is None:
                    info["last_run"] = info["last_run"].isoformat() + "Z"
                else:
                    info["last_run"] = info["last_run"].isoformat()

        result.append(info)

    return result


async def reschedule_playlist_update(hour: int, minute: int) -> str | None:
    """Reschedule the daily playlist update and persist the new time.

    Returns the next run time ISO string, or None on failure.
    """
    try:
        scheduler.reschedule_job(
            "daily_playlist_update",
            trigger=CronTrigger(hour=hour, minute=minute),
        )

        # Persist to database
        async with async_session_maker() as db:
            for key, value in [("playlist_update_hour", str(hour)), ("playlist_update_minute", str(minute))]:
                result = await db.execute(select(AppSetting).where(AppSetting.key == key))
                setting = result.scalar_one_or_none()
                if setting:
                    setting.value = value
                else:
                    db.add(AppSetting(key=key, value=value))
            await db.commit()

        # Get updated next run time
        job = scheduler.get_job("daily_playlist_update")
        next_run = job.next_run_time.isoformat() if job and job.next_run_time else None

        logger.info(f"Rescheduled daily playlist update to {hour:02d}:{minute:02d}, next run: {next_run}")
        return next_run
    except Exception as e:
        logger.error(f"Failed to reschedule daily playlist update: {e}")
        raise


async def trigger_playlist_update_for_user(user_id: int) -> dict:
    """Manually trigger playlist update for a specific user.

    Args:
        user_id: The user ID to update playlists for.

    Returns:
        Dictionary with update results.
    """
    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

            if not user:
                return {"success": False, "error": "User not found"}

            builder = PlaylistBuilder(db, user)
            results = await builder.update_all_playlists()
            await db.commit()

            return {
                "success": True,
                "results": [
                    {
                        "playlist_id": r.playlist_id,
                        "playlist_name": r.playlist_name,
                        "success": r.success,
                        "episode_count": r.episode_count,
                        "error": r.error,
                    }
                    for r in results
                ],
            }

        except Exception as e:
            logger.error(f"Manual playlist update failed: {e}")
            await db.rollback()
            return {"success": False, "error": str(e)}


async def trigger_single_playlist_update(user_id: int, playlist_id: int) -> dict:
    """Manually trigger update for a single playlist.

    Args:
        user_id: The user ID.
        playlist_id: The playlist ID to update.

    Returns:
        Dictionary with update result.
    """
    async with async_session_maker() as db:
        try:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()

            if not user:
                return {"success": False, "error": "User not found"}

            playlist_result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
            playlist = playlist_result.scalar_one_or_none()

            if not playlist:
                return {"success": False, "error": "Playlist not found"}

            builder = PlaylistBuilder(db, user)
            result = await builder.update_playlist(playlist)
            await db.commit()

            return {
                "success": result.success,
                "playlist_id": result.playlist_id,
                "playlist_name": result.playlist_name,
                "episode_count": result.episode_count,
                "error": result.error,
            }

        except Exception as e:
            logger.error(f"Single playlist update failed: {e}")
            await db.rollback()
            return {"success": False, "error": str(e)}


async def _get_valid_access_token(user_id: int) -> str | None:
    """Get a valid Spotify access token for a user, refreshing if expired.

    Uses a short-lived DB session to read/update tokens.

    Args:
        user_id: The user ID.

    Returns:
        A valid access token string, or None if the user was not found.
    """
    encryption = get_encryption_service()

    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None

        access_token = encryption.decrypt(user.access_token)
        token_exp = user.token_expires_at.replace(tzinfo=UTC) if user.token_expires_at.tzinfo is None else user.token_expires_at

        if datetime.now(UTC) >= token_exp:
            refresh_token = encryption.decrypt(user.refresh_token)
            spotify = SpotifyService()
            token_data = await spotify.refresh_access_token(refresh_token)
            user.access_token = encryption.encrypt(token_data["access_token"])
            user.refresh_token = encryption.encrypt(token_data["refresh_token"])
            user.token_expires_at = token_data["expires_at"]
            await db.commit()
            access_token = token_data["access_token"]

        return access_token


async def remove_played_episodes_from_playlists() -> None:
    """Remove fully-played episodes from all playlists for all users.

    This job runs every 5 minutes to clean up played content.
    Uses short-lived DB sessions to avoid holding write locks during Spotify API calls.
    """
    _record_run("remove_played_episodes")
    logger.info("Starting remove played episodes job")

    # Phase 1: Read users and playlists with a short-lived session
    user_playlists: list[tuple[int, list[tuple[int, str, str]]]] = []  # [(user_id, [(playlist_id, name, spotify_id)])]
    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User))
            users = result.scalars().all()

            for user in users:
                playlists_result = await db.execute(
                    select(Playlist).where((Playlist.user_id == user.id) & (Playlist.is_enabled == True))
                )
                playlists = playlists_result.scalars().all()

                playlist_info = [
                    (p.id, p.name, p.spotify_playlist_id)
                    for p in playlists
                    if p.spotify_playlist_id
                ]
                if playlist_info:
                    user_playlists.append((user.id, playlist_info))
        except Exception as e:
            logger.error(f"Remove played episodes job failed reading DB: {e}")
            return

    # Phase 2: Process each playlist with Spotify API calls (no DB session held)
    total_removed = 0
    errors = []

    for user_id, playlists in user_playlists:
        try:
            access_token = await _get_valid_access_token(user_id)
            if not access_token:
                logger.warning(f"User {user_id} not found, skipping")
                continue

            spotify_client = SpotifyService(access_token=access_token)

            for playlist_id, playlist_name, spotify_playlist_id in playlists:
                try:
                    # Get all tracks in playlist (Spotify API only, no DB)
                    offset = 0
                    limit = 50
                    playlist_episode_ids: list[str] = []

                    while True:
                        tracks_data = await spotify_client.get_playlist_tracks(
                            spotify_playlist_id, limit=limit, offset=offset
                        )
                        tracks = tracks_data.get("items", [])

                        if not tracks:
                            break

                        for track in tracks:
                            if track and "track" in track:
                                episode = track["track"]
                                uri = episode.get("uri")
                                if uri and uri.startswith("spotify:episode:"):
                                    ep_id = uri.split(":")[-1]
                                    playlist_episode_ids.append(ep_id)

                        offset += limit
                        if not tracks_data.get("next"):
                            break

                    # Fetch detailed episode objects to check play status
                    played_uris: list[str] = []
                    try:
                        for i in range(0, len(playlist_episode_ids), 50):
                            batch_ids = playlist_episode_ids[i : i + 50]
                            details = await spotify_client.get_episodes(batch_ids)
                            for ep in details:
                                if not ep:
                                    continue
                                resume_point = ep.get("resume_point") or {}
                                if resume_point.get("fully_played", False):
                                    played_uris.append(ep.get("uri") or f"spotify:episode:{ep['id']}")
                    except Exception as e:
                        logger.error(f"Failed to fetch episode details for playlist cleanup: {e}")

                    # Remove played episodes if any found
                    if played_uris:
                        logger.info(
                            f"Playlist {playlist_name} ({spotify_playlist_id}) - found {len(played_uris)} fully-played episodes: {played_uris}"
                        )
                        for i in range(0, len(played_uris), 50):
                            batch = played_uris[i : i + 50]
                            try:
                                logger.info(
                                    f"Attempting to remove batch of {len(batch)} from playlist {playlist_name} (user {user_id}): {batch}"
                                )
                                await spotify_client.remove_tracks_from_playlist(
                                    spotify_playlist_id, batch
                                )
                                total_removed += len(batch)
                                logger.info(
                                    f"Removed {len(batch)} played episodes from playlist {playlist_name} (user {user_id})"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to remove batch from playlist {playlist_name} (user {user_id}): {e} - batch: {batch}"
                                )

                except Exception as e:
                    logger.error(f"Failed to clean playlist {playlist_name} (user {user_id}): {e}")
                    errors.append(f"Playlist {playlist_name}: {str(e)}")

        except Exception as e:
            logger.error(f"Failed to clean playlists for user {user_id}: {e}")
            errors.append(f"User {user_id}: {str(e)}")

    logger.info(f"Remove played episodes job completed: removed {total_removed} episodes, {len(errors)} errors")
