"""SyncLog run bookkeeping shared by the scheduled jobs.

Every job that records its runs writes a ``RUNNING`` row first and finalises
it on the way out (issue #174). :func:`sync_log_run` owns both halves, so a
job cannot leave its row ``RUNNING`` by forgetting the second one; the
startup sweep in :func:`fail_orphaned_sync_logs` covers the process itself
dying mid-run (issue #161).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.database import async_session_maker
from app.models.sync_log import SyncLog, SyncStatus
from app.services.encryption import is_unreadable_credentials

logger = logging.getLogger(__name__)

# failure_code for a run that hit stored Spotify tokens it could not decrypt
# (issue #308). The user has to sign in again; Spotify itself refused nothing.
CREDENTIALS_UNREADABLE_FAILURE_CODE = "credentials_unreadable"

# failure_code written by the startup sweep below. Distinct from the codes
# classify_failure produces so the history can tell "the job broke" apart
# from "the process went away underneath the job".
INTERRUPTED_FAILURE_CODE = "interrupted"


@dataclass
class SyncLogRun:
    """One job run's SyncLog row and the outcome to write onto it.

    ``id`` is None when the row could not be created; the run goes ahead
    regardless and finalising it is then a no-op.
    """

    job_type: str
    id: int | None = None
    outcome: dict | None = field(default=None, repr=False)

    def finish(
        self,
        *,
        status: SyncStatus,
        details: str,
        failure_code: str | None,
        playlists_attempted: int = 0,
        playlists_failed: int = 0,
        api_calls_used: int | None = None,
    ) -> None:
        """Record the outcome written when the ``sync_log_run`` block exits."""
        self.outcome = {
            "status": status,
            "details": details,
            "failure_code": failure_code,
            "playlists_attempted": playlists_attempted,
            "playlists_failed": playlists_failed,
            "api_calls_used": api_calls_used,
        }

    def fail(self, details: str, failure_code: str = "unknown") -> None:
        """Shorthand for a failed outcome with nothing counted."""
        self.finish(status=SyncStatus.FAILED, details=details, failure_code=failure_code)


@asynccontextmanager
async def sync_log_run(job_type: str) -> AsyncIterator[SyncLogRun]:
    """Write a ``RUNNING`` SyncLog row and always finalise it on exit.

    The body reports its outcome with :meth:`SyncLogRun.finish` (or
    :meth:`SyncLogRun.fail`). If it raises first, the row is finalised as
    ``FAILED`` and the exception propagates; if it returns without an
    outcome, that is a bug in the job, and the row is still closed out as
    ``FAILED`` rather than left ``RUNNING``.
    """
    run = SyncLogRun(job_type)
    try:
        async with async_session_maker() as db:
            sync_log = SyncLog(job_type=job_type, status=SyncStatus.RUNNING, started_at=datetime.now(UTC))
            db.add(sync_log)
            await db.commit()
            run.id = sync_log.id
    except Exception as e:
        logger.error(f"{job_type} job failed creating sync log: {e}")

    try:
        yield run
    except Exception as e:
        if run.outcome is None:
            run.fail(f"Job failed unexpectedly: {e}")
        raise
    finally:
        if run.outcome is None:
            run.fail("Job ended without recording an outcome")
        await finalise_sync_log(run.id, **run.outcome)


async def finalise_sync_log(
    sync_log_id: int | None,
    *,
    status: SyncStatus,
    details: str,
    failure_code: str | None,
    playlists_attempted: int = 0,
    playlists_failed: int = 0,
    api_calls_used: int | None = None,
) -> None:
    """Write the final outcome onto a RUNNING SyncLog row.

    Never raises: a failed write is logged, and the startup sweep closes the
    row out on the next restart.
    """
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
            logger.error(f"Failed to update sync log: {e}")


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
    sweep is exact. Called from ``init_scheduler``; a failure here is
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


def classify_failure(
    *,
    playlists_attempted: int,
    playlists_failed: int,
    error_messages: list[str],
    exceptions: list[BaseException],
) -> str | None:
    """Classify the failure mode of a playlist job for SyncLog.

    Classification uses only structured data: the ``httpx.HTTPStatusError``
    found in each exception or its ``__cause__`` / ``__context__`` chain
    (``EpisodeFetchError`` wraps the HTTP error with ``raise ... from``).
    ``error_messages`` are never searched — they contain user-chosen names,
    and a playlist called "Top 401" used to classify as ``token_expired``.

    Returns:
        One of: credentials_unreadable, rate_limit, token_expired,
        playlist_write_failed, partial, unknown — or None if there were no
        failures.
    """
    if not error_messages and not exceptions:
        return None

    # Stored tokens that can't be decrypted are not a Spotify failure: no
    # request was refused, and no retry helps until the user signs in again
    # (issue #308). They outrank everything else for that reason.
    if any(is_unreadable_credentials(exc) for exc in exceptions):
        return CREDENTIALS_UNREADABLE_FAILURE_CODE

    statuses: list[int] = []
    methods: list[str] = []
    for exc in exceptions:
        http_error = _find_http_status_error(exc)
        if http_error is not None:
            statuses.append(http_error.response.status_code)
            methods.append(http_error.request.method.upper())

    if 429 in statuses:
        return "rate_limit"
    if 401 in statuses:
        return "token_expired"

    write_methods = {"PUT", "POST", "DELETE"}
    for status, method in zip(statuses, methods, strict=False):
        if method in write_methods and 400 <= status < 600:
            return "playlist_write_failed"

    if playlists_failed and playlists_failed < playlists_attempted:
        return "partial"

    return "unknown"


def _find_http_status_error(exc: BaseException) -> httpx.HTTPStatusError | None:
    """The first ``httpx.HTTPStatusError`` in ``exc``'s cause/context chain."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, httpx.HTTPStatusError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None
