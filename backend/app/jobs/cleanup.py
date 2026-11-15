"""The cleanup job: remove fully-played episodes from the managed playlists."""

import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import async_session_maker
from app.jobs import locks
from app.jobs.playlist_update import PLAYLIST_UPDATE_JOB_TYPE
from app.jobs.schedule import upsert_app_setting
from app.jobs.sync_log import classify_failure, sync_log_run
from app.models.playlist import Playlist, PlaylistKind
from app.models.settings import AppSetting
from app.models.sync_log import SyncLog, SyncStatus
from app.models.user import User
from app.services.encryption import is_unreadable_credentials
from app.services.spotify import CleanupBudgetExceeded, SpotifyService
from app.services.token_manager import TokenManager

CLEANUP_JOB_TYPE = "cleanup"

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

logger = logging.getLogger(__name__)


def _cleanup_candidates():
    """Playlists the cleanup job may remove played episodes from.

    Enabled ones only (issue #239), and never a sleep playlist, which is
    made of played episodes on purpose (issue #331).
    """
    return Playlist.is_enabled.is_(True) & (Playlist.kind != PlaylistKind.SLEEP.value)


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
            result = await db.execute(select(Playlist).where(_cleanup_candidates()))
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
                    (SyncLog.job_type == PLAYLIST_UPDATE_JOB_TYPE)
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

    # The SyncLog row is written only past the recency gate: a skipped run
    # did no work and must not show up as the last run.
    async with sync_log_run(CLEANUP_JOB_TYPE) as run:
        # Phase 1: Read users, playlists and the rotation cursor with a
        # short-lived session
        rotation_offset = 0
        user_playlists: list[
            tuple[int, list[tuple[int, str, str]]]
        ] = []  # [(user_id, [(playlist_id, name, spotify_id)])]
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
                    # Sleep playlists hold played episodes by design (issue #331);
                    # cleanup would empty them.
                    playlists_result = await db.execute(
                        select(Playlist).where((Playlist.user_id == user.id) & _cleanup_candidates())
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
            run.finish(
                status=SyncStatus.FAILED,
                details=f"Failed reading users/playlists: {read_error}",
                failure_code="unknown",
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
                        if is_unreadable_credentials(e):
                            logger.error(f"Cleanup skipped user {user_id}: stored credentials are unreadable")
                        else:
                            logger.error(f"Failed to get token for user {user_id}: {e}")
                        errors.append(f"User {user_id}: {str(e)}")
                        error_objects.append(e)
                        continue

                    spotify_client = SpotifyService(access_token=access_token)

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
                                                spotify_client.set_access_token(
                                                    await token_manager.get_token(min_remaining_seconds=300)
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
            # something still escapes it, report it as this run's failure
            # rather than as an unexpected crash.
            logger.error(f"Cleanup job failed unexpectedly: {e}")
            errors.append(str(e))
            error_objects.append(e)

        # The row is finalised as the block exits, before the rotation-cursor
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
            failure_code = classify_failure(
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

        run.finish(
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
            await upsert_app_setting(db, CLEANUP_ROTATION_KEY, str(offset))
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to persist cleanup rotation cursor: {e}")
