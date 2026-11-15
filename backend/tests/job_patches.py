"""Patching helpers for the scheduled-job modules under ``app.jobs``."""

from contextlib import ExitStack, contextmanager
from unittest.mock import patch

# Every job module that opens its own DB sessions. A job run can touch
# several of them (the SyncLog row is written by app.jobs.sync_log, the
# work by the job's own module), so tests swap the session maker in all.
JOB_MODULES_WITH_SESSIONS = (
    "app.jobs.cleanup",
    "app.jobs.manual_run",
    "app.jobs.playlist_update",
    "app.jobs.schedule",
    "app.jobs.scheduler",
    "app.jobs.status",
    "app.jobs.sync_log",
)


@contextmanager
def patch_job_sessions(session_maker):
    """Point every job module's ``async_session_maker`` at ``session_maker``."""
    with ExitStack() as stack:
        for module in JOB_MODULES_WITH_SESSIONS:
            stack.enter_context(patch(f"{module}.async_session_maker", session_maker))
        yield session_maker
