"""The daily job: sync every library from Spotify, then rebuild every playlist."""

import logging

from sqlalchemy import select

from app.database import async_session_maker
from app.jobs import locks
from app.jobs.sync_log import CREDENTIALS_UNREADABLE_FAILURE_CODE, classify_failure, sync_log_run
from app.models.sync_log import SyncStatus
from app.models.user import User
from app.services.encryption import is_unreadable_credentials
from app.services.library_sync import sync_library
from app.services.playlist_builder import PlaylistBuilder
from app.services.spotify import SpotifyService
from app.services.token_manager import TokenManager

LIBRARY_SYNC_JOB_TYPE = "library_sync"
PLAYLIST_UPDATE_JOB_TYPE = "playlist_update"

logger = logging.getLogger(__name__)


async def _read_user_ids() -> list[int]:
    async with async_session_maker() as db:
        result = await db.execute(select(User.id))
        return [row[0] for row in result.all()]


async def sync_all_libraries() -> None:
    """Refresh every user's podcast library from Spotify.

    Runs as the first step of :func:`update_all_playlists` (issue #240). Until
    this existed, nothing pulled ``GET /me/shows`` on a schedule: a new
    subscription stayed invisible until someone pressed Sync, and the
    unsubscribe reconcile from issue #155 — including the grace-period
    deletion — only ever advanced when a human happened to press the button.

    Failures are recorded in the job's own ``library_sync`` SyncLog row and
    never abort the rebuild that follows — a stale library is a much smaller
    problem than a day with no playlist update. ``get_job_status`` folds that
    row into the daily job's reported status, so a sync that failed under a
    successful rebuild still shows up in the UI.

    Serialised against a manual ``POST /podcasts/sync`` through
    ``library_sync_lock``; see the lock's own note for why two concurrent
    walks are unsafe.
    """
    logger.info("Starting library sync job")

    async with sync_log_run(LIBRARY_SYNC_JOB_TYPE) as run:
        try:
            user_ids = await _read_user_ids()
        except Exception as e:
            logger.error(f"Library sync job failed reading users: {e}")
            run.fail(f"Failed reading users: {e}")
            return

        summaries: list[str] = []
        errors: list[str] = []
        credentials_unreadable = False

        # The lock covers each user's commit, not just its walk: releasing
        # before the commit would leave the pending insert invisible to a
        # concurrent sync, which is the whole race it exists to close.
        if locks.library_sync_lock.locked():
            logger.info("Waiting on library_sync_lock — a manual sync is running")
        async with locks.library_sync_lock:
            for user_id in user_ids:
                async with async_session_maker() as db:
                    try:
                        token_manager = TokenManager(user_id)
                        access_token = await token_manager.get_token(min_remaining_seconds=300)
                        # One httpx client for the whole /me/shows walk.
                        async with SpotifyService(access_token=access_token) as spotify:
                            result = await sync_library(db, spotify, on_unauthorized=token_manager.force_refresh)
                        await db.commit()
                        summaries.append(f"User {user_id}: {result.summary}")
                    except Exception as e:
                        # A partial walk leaves uncommitted upserts and, by
                        # construction, no reconciliation — roll the lot back
                        # so the library is never half-updated from a half-read.
                        if is_unreadable_credentials(e):
                            credentials_unreadable = True
                            logger.error(f"Library sync skipped user {user_id}: stored credentials are unreadable")
                        else:
                            logger.error(f"Library sync failed for user {user_id}: {e}")
                        errors.append(f"User {user_id}: {e}")
                        await db.rollback()

        details = "; ".join(summaries) if summaries else "No users synced."
        if errors:
            details += f"\nErrors: {chr(10).join(errors[:10])}"

        run.finish(
            status=SyncStatus.SUCCESS if not errors else SyncStatus.FAILED,
            details=details,
            failure_code=(
                None if not errors else CREDENTIALS_UNREADABLE_FAILURE_CODE if credentials_unreadable else "unknown"
            ),
        )

    logger.info(f"Library sync job completed: {details}")


async def update_all_playlists() -> None:
    """Update all enabled playlists for all users.

    Uses a separate DB session per user so that Spotify API calls for one user
    don't hold a write lock that blocks the rest of the application.
    """
    logger.info("Starting daily playlist update job")

    # Pull the library first so the rebuild sees today's subscriptions and
    # skips shows unfollowed on Spotify (issue #240). Deliberately outside
    # the playlist write lock: it only touches the podcasts table, and the
    # /me/shows walk shouldn't hold a lock the cleanup job is waiting on.
    try:
        await sync_all_libraries()
    except Exception as e:
        # sync_all_libraries handles its own failures; anything escaping it
        # must still not stop the rebuild.
        logger.error(f"Library sync step failed, continuing with the rebuild: {e}")

    async with sync_log_run(PLAYLIST_UPDATE_JOB_TYPE) as run:
        try:
            user_ids = await _read_user_ids()
        except Exception as e:
            logger.error(f"Playlist update job failed reading users: {e}")
            run.fail(f"Failed reading users: {e}")
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
                                    # Disabled playlist — deliberately untouched,
                                    # so don't count it as an attempted rebuild (#239).
                                    playlists_skipped += 1
                                    continue
                                total_playlists += 1
                                if res.success:
                                    total_episodes += res.episode_count
                                else:
                                    playlists_failed += 1
                                    errors.append(f"{res.playlist_name}: {res.error}")
                                    if res.exception is not None:
                                        error_objects.append(res.exception)

                            await db.commit()

                        except Exception as e:
                            logger.error(f"Failed to update playlists for user {user_id}: {e}")
                            errors.append(f"User {user_id}: {str(e)}")
                            error_objects.append(e)
                            await db.rollback()
        except Exception as e:
            # The per-user try above is the intended last line of defence; if
            # something still escapes it, report it as this run's failure
            # rather than as an unexpected crash.
            logger.error(f"Playlist update job failed unexpectedly: {e}")
            errors.append(str(e))
            error_objects.append(e)

        details = f"Updated {total_playlists} playlists with {total_episodes} episodes. Errors: {len(errors)}"
        if playlists_skipped:
            details += f" Skipped (disabled): {playlists_skipped}."
        if errors:
            details += f"\n{chr(10).join(errors[:10])}"

        run.finish(
            status=SyncStatus.SUCCESS if not errors else SyncStatus.FAILED,
            details=details,
            # Failure classification (issue #89, PR1).
            failure_code=classify_failure(
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
