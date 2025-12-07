"""APScheduler setup and job management."""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_maker
from app.models.playlist import Playlist
from app.models.sync_log import SyncLog, SyncStatus
from app.models.user import User
from app.services.encryption import get_encryption_service
from app.services.playlist_builder import PlaylistBuilder
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)
settings = get_settings()

# Global scheduler instance
scheduler = AsyncIOScheduler()


async def refresh_all_tokens() -> None:
    """Refresh Spotify tokens for all users before they expire."""
    logger.info("Starting token refresh job")

    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User))
            users = result.scalars().all()

            encryption = get_encryption_service()

            for user in users:
                try:
                    # Check if token will expire in the next 15 minutes
                    if (user.token_expires_at.timestamp() - datetime.utcnow().timestamp()) < 900:
                        refresh_token = encryption.decrypt(user.refresh_token)
                        spotify = SpotifyService()
                        token_data = await spotify.refresh_access_token(refresh_token)

                        user.access_token = encryption.encrypt(token_data["access_token"])
                        user.refresh_token = encryption.encrypt(token_data["refresh_token"])
                        user.token_expires_at = token_data["expires_at"]

                        logger.info(f"Refreshed token for user {user.display_name}")

                except Exception as e:
                    logger.error(f"Failed to refresh token for user {user.id}: {e}")

            await db.commit()
            logger.info("Token refresh job completed")

        except Exception as e:
            logger.error(f"Token refresh job failed: {e}")
            await db.rollback()


async def update_all_playlists() -> None:
    """Update all enabled playlists for all users."""
    logger.info("Starting daily playlist update job")

    async with async_session_maker() as db:
        try:
            # Create sync log entry
            sync_log = SyncLog(
                job_type="playlist_update",
                status=SyncStatus.RUNNING,
                started_at=datetime.utcnow(),
            )
            db.add(sync_log)
            await db.flush()

            # Get all users
            result = await db.execute(select(User))
            users = result.scalars().all()

            total_playlists = 0
            total_episodes = 0
            errors = []

            for user in users:
                try:
                    builder = PlaylistBuilder(db, user)
                    results = await builder.update_all_playlists()

                    for res in results:
                        total_playlists += 1
                        if res.success:
                            total_episodes += res.episode_count
                        else:
                            errors.append(f"{res.playlist_name}: {res.error}")

                except Exception as e:
                    logger.error(f"Failed to update playlists for user {user.id}: {e}")
                    errors.append(f"User {user.id}: {str(e)}")

            # Update sync log
            sync_log.status = SyncStatus.SUCCESS if not errors else SyncStatus.FAILED
            sync_log.completed_at = datetime.utcnow()
            sync_log.details = (
                f"Updated {total_playlists} playlists with {total_episodes} episodes. "
                f"Errors: {len(errors)}"
            )
            if errors:
                sync_log.details += f"\n{chr(10).join(errors[:10])}"  # First 10 errors

            await db.commit()
            logger.info(
                f"Playlist update job completed: {total_playlists} playlists, "
                f"{total_episodes} episodes, {len(errors)} errors"
            )

        except Exception as e:
            logger.error(f"Playlist update job failed: {e}")
            await db.rollback()


def init_scheduler() -> None:
    """Initialize and start the scheduler with configured jobs."""
    if scheduler.running:
        return

    # Daily playlist update job
    scheduler.add_job(
        update_all_playlists,
        CronTrigger(
            hour=settings.PLAYLIST_UPDATE_HOUR,
            minute=settings.PLAYLIST_UPDATE_MINUTE,
        ),
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
    scheduler.add_job(
        remove_played_episodes_from_playlists,
        IntervalTrigger(minutes=5),
        id="remove_played_episodes",
        name="Remove Played Episodes",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started with daily update at "
        f"{settings.PLAYLIST_UPDATE_HOUR:02d}:{settings.PLAYLIST_UPDATE_MINUTE:02d}"
    )


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler shutdown complete")


def get_job_status() -> list[dict]:
    """Get status of all scheduled jobs."""
    jobs = scheduler.get_jobs()
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        }
        for job in jobs
    ]


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

            playlist_result = await db.execute(
                select(Playlist).where(Playlist.id == playlist_id)
            )
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


async def remove_played_episodes_from_playlists() -> None:
    """Remove fully-played episodes from all playlists for all users.

    This job runs every 5 minutes to clean up played content.
    """
    logger.info("Starting remove played episodes job")

    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User))
            users = result.scalars().all()

            encryption = get_encryption_service()
            total_removed = 0
            errors = []

            for user in users:
                try:
                    # Get all enabled playlists for user
                    playlists_result = await db.execute(
                        select(Playlist).where(
                            (Playlist.user_id == user.id) & (Playlist.is_enabled == True)
                        )
                    )
                    playlists = playlists_result.scalars().all()

                    for playlist in playlists:
                        try:
                            # Get Spotify client with valid token
                            access_token = encryption.decrypt(user.access_token)
                            if datetime.utcnow() >= user.token_expires_at:
                                refresh_token = encryption.decrypt(user.refresh_token)
                                spotify = SpotifyService()
                                token_data = await spotify.refresh_access_token(
                                    refresh_token
                                )
                                user.access_token = encryption.encrypt(
                                    token_data["access_token"]
                                )
                                user.refresh_token = encryption.encrypt(
                                    token_data["refresh_token"]
                                )
                                user.token_expires_at = token_data["expires_at"]
                                await db.flush()
                                access_token = token_data["access_token"]

                            spotify_client = SpotifyService(access_token=access_token)

                            # Get all tracks in playlist
                            offset = 0
                            limit = 50

                            # Collect episode ids found in the playlist so we can
                            # fetch detailed episode objects (which include
                            # `resume_point`) since playlist track objects may not.
                            playlist_episode_ids: list[str] = []

                            while True:
                                tracks_data = await spotify_client.get_playlist_tracks(
                                    playlist.spotify_playlist_id, limit=limit, offset=offset
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

                            # Fetch detailed episode objects in batches and
                            # determine which are fully played for this user.
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
                                    f"Playlist {playlist.name} ({playlist.spotify_playlist_id}) - found {len(played_uris)} fully-played episodes: {played_uris}"
                                )
                                # Remove in batches to avoid timeouts
                                for i in range(0, len(played_uris), 50):
                                    batch = played_uris[i : i + 50]
                                    try:
                                        logger.info(
                                            f"Attempting to remove batch of {len(batch)} from playlist {playlist.name} (user {user.id}): {batch}"
                                        )
                                        await spotify_client.remove_tracks_from_playlist(
                                            playlist.spotify_playlist_id, batch
                                        )
                                        total_removed += len(batch)
                                        logger.info(
                                            f"Removed {len(batch)} played episodes from playlist {playlist.name} (user {user.id})"
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"Failed to remove batch from playlist {playlist.name} (user {user.id}): {e} - batch: {batch}"
                                        )

                        except Exception as e:
                            logger.error(
                                f"Failed to clean playlist {playlist.name} "
                                f"(user {user.id}): {e}"
                            )
                            errors.append(
                                f"Playlist {playlist.name}: {str(e)}"
                            )

                    await db.commit()

                except Exception as e:
                    logger.error(f"Failed to clean playlists for user {user.id}: {e}")
                    errors.append(f"User {user.id}: {str(e)}")
                    await db.rollback()

            logger.info(
                f"Remove played episodes job completed: "
                f"removed {total_removed} episodes, {len(errors)} errors"
            )

        except Exception as e:
            logger.error(f"Remove played episodes job failed: {e}")
            await db.rollback()
