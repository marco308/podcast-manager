"""Manual playlist runs: ``POST /playlists/{id}/run`` and ``/run-all`` (issue #242).

A manual run is recorded in SyncLog as ``manual_playlist_update``, whichever
way it is served. Synchronously, the request does the work and answers with
the result, as it always has (installed iOS builds rely on that). With
``Prefer: respond-async`` the request only takes the write lock and records
the run, answers ``202`` with the run's id, and the work carries on here, in
a background task the client polls through ``GET /api/jobs/runs/{id}`` —
so nginx's 30s ``proxy_read_timeout`` can no longer cut a long build off.

The lock hand-off: the request acquires ``playlist_write_lock`` *before* it
answers and pushes its release onto an :class:`~contextlib.AsyncExitStack`
together with the run's :func:`sync_log_run`. The background task owns that
stack and closes it when the work ends, on every path: the SyncLog row is
finalised, then the lock released. There is no moment between the 202 and the
task when the lock is free, so a second run, the cleanup job or an account
deletion can't slip in; deletion waits for the lock and answers 409.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack

from app.database import async_session_maker
from app.jobs.sync_log import SyncLogRun, classify_failure
from app.models.playlist import Playlist
from app.models.sync_log import SyncStatus
from app.models.user import User
from app.services.encryption import is_unreadable_credentials
from app.services.playlist_builder import PlaylistBuilder, PlaylistUpdateResult
from app.services.token_manager import TokenManager

logger = logging.getLogger(__name__)

MANUAL_PLAYLIST_UPDATE_JOB_TYPE = "manual_playlist_update"

# What a client is told about a failed playlist. The detail is logged, not
# handed to the client (issue #161).
GENERIC_FAILURE = "Failed to update playlist. Check the server logs for details."

# What a client is told when the stored Spotify tokens can't be decrypted
# (issue #308). Same words as the synchronous path's 401.
CREDENTIALS_UNREADABLE_MESSAGE = "Stored credentials could not be read. Please sign in again."

# Background runs in flight. The event loop only keeps weak references to
# tasks, so without this a run could be garbage-collected mid-build.
_background_runs: set[asyncio.Task] = set()


def credentials_unreadable(results: list[PlaylistUpdateResult]) -> bool:
    """Whether any result failed on stored tokens that can't be decrypted."""
    return any(r.exception is not None and is_unreadable_credentials(r.exception) for r in results)


def result_entry(r: PlaylistUpdateResult) -> dict:
    """One playlist's client-facing outcome, as ``/run-all`` returns it."""
    if r.partial:
        # Names the podcasts we couldn't reach: ours, not exception text.
        error = r.error
    elif r.error:
        error = GENERIC_FAILURE
    else:
        error = None
    return {
        "playlist_id": r.playlist_id,
        "playlist_name": r.playlist_name,
        "success": r.success,
        "episode_count": r.episode_count,
        "error": error,
        "partial": r.partial,
        "skipped": r.skipped,
    }


def single_run_message(r: PlaylistUpdateResult) -> str:
    """The message ``POST /playlists/{id}/run`` gives for its one result."""
    if r.skipped:
        return f"Playlist '{r.playlist_name}' is disabled and was left unchanged"
    if r.partial:
        return f"Playlist '{r.playlist_name}' updated with warnings: {r.error}"
    if r.success:
        return f"Playlist '{r.playlist_name}' updated successfully"
    if credentials_unreadable([r]):
        return CREDENTIALS_UNREADABLE_MESSAGE
    return GENERIC_FAILURE


def run_all_message(results: list[PlaylistUpdateResult]) -> str:
    """The message ``POST /playlists/run-all`` gives for its results."""
    if credentials_unreadable(results):
        return CREDENTIALS_UNREADABLE_MESSAGE
    skipped = [r for r in results if r.skipped]
    partial = [r for r in results if r.partial]
    successful = [r for r in results if r.success and not r.skipped]
    failed = [r for r in results if not r.success and not r.partial]
    message = f"Updated {len(successful)} playlists, {len(failed)} failed"
    if partial:
        message += f", {len(partial)} updated with warnings"
    if skipped:
        message += f", {len(skipped)} skipped (disabled)"
    return message


def record_outcome(run: SyncLogRun, results: list[PlaylistUpdateResult], *, message: str) -> None:
    """Write a manual run's results onto its SyncLog row.

    Counted like the daily rebuild: a skipped (disabled) playlist is not an
    attempt, and a partial one counts as failed, because the playlist is not a
    faithful rebuild (issue #145). ``outcome`` keeps what the client is shown.
    """
    attempted = [r for r in results if not r.skipped]
    failed = [r for r in attempted if not r.success]
    errors = [f"{r.playlist_name}: {r.error}" for r in failed]
    failure_code = classify_failure(
        playlists_attempted=len(attempted),
        playlists_failed=len(failed),
        error_messages=errors,
        exceptions=[r.exception for r in failed if r.exception is not None],
    )
    if failure_code == "unknown" and failed and all(r.partial for r in failed):
        # classify_failure only says "partial" when some playlists succeeded;
        # a one-playlist run written from incomplete data is partial too.
        failure_code = "partial"

    details = f"Manual run: {message}."
    if errors:
        details += "\n" + "\n".join(errors[:10])

    run.finish(
        status=SyncStatus.SUCCESS if not failed else SyncStatus.FAILED,
        details=details,
        failure_code=failure_code,
        playlists_attempted=len(attempted),
        playlists_failed=len(failed),
        outcome={"message": message, "results": [result_entry(r) for r in results]},
    )


async def run_one_playlist(run: SyncLogRun, user_id: int, playlist_id: int) -> None:
    """The background half of an async ``POST /playlists/{id}/run``."""
    async with async_session_maker() as db:
        user = await db.get(User, user_id)
        playlist = await db.get(Playlist, playlist_id)
        if user is None or playlist is None:
            # Can't normally happen: deleting either takes the write lock this
            # run holds. Recorded rather than raised, so the poll says why.
            run.fail("The playlist no longer exists.", failure_code="not_found")
            return
        builder = PlaylistBuilder(db, user, token_manager=TokenManager(user.id))
        result = await builder.update_playlist(playlist)
        await db.commit()
    if not result.success and not result.partial:
        logger.error(f"Manual run failed for playlist '{result.playlist_name}': {result.error}")
    record_outcome(run, [result], message=single_run_message(result))


async def run_all_playlists(run: SyncLogRun, user_id: int) -> None:
    """The background half of an async ``POST /playlists/run-all``."""
    async with async_session_maker() as db:
        user = await db.get(User, user_id)
        if user is None:
            run.fail("The account no longer exists.", failure_code="not_found")
            return
        builder = PlaylistBuilder(db, user, token_manager=TokenManager(user.id))
        results = await builder.update_all_playlists()
        await db.commit()
    for r in results:
        if not r.success and not r.partial:
            logger.error(f"Manual run-all failed for playlist '{r.playlist_name}': {r.error}")
    record_outcome(run, results, message=run_all_message(results))


def start_in_background(
    stack: AsyncExitStack,
    run: SyncLogRun,
    work: Callable[[SyncLogRun], Awaitable[None]],
) -> asyncio.Task:
    """Run ``work`` in a background task that owns ``stack``.

    ``stack`` holds the run's ``sync_log_run`` and the release of the write
    lock the request acquired; closing it at the end of the task, however
    the work ends, finalises the row and then frees the lock.
    """

    async def drive() -> None:
        try:
            async with stack:
                await work(run)
        except Exception:
            # sync_log_run has already marked the row FAILED; nobody awaits
            # this task, so log it here rather than as "never retrieved".
            logger.exception(f"Manual run {run.id} failed unexpectedly")

    task = asyncio.create_task(drive(), name=f"manual-run-{run.id}")
    _background_runs.add(task)
    task.add_done_callback(_background_runs.discard)
    return task
