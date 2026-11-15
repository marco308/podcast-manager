"""Jobs API router."""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jobs.scheduler import MAX_PLAYLIST_UPDATE_TIMES, get_job_status, reschedule_playlist_update
from app.models.session import Session
from app.models.sync_log import SyncLog
from app.rate_limit import limiter
from app.routers.auth import get_current_user_id, validate_csrf_token
from app.schemas.playlist import DB_ID_MAX, RunAllPlaylistResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


class ScheduleTime(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)


class JobStatus(BaseModel):
    """One scheduled job, as built by ``get_job_status``.

    The fields with a default are only sent for some jobs (the route uses
    ``response_model_exclude_unset``): the ``schedule*`` fields for cron
    jobs, ``max_schedule_times`` for the configurable one,
    ``interval_minutes`` for interval jobs and ``last_run_failed_steps`` when
    a step of the last run failed.
    """

    id: str
    name: str
    next_run: str | None
    last_run: str | None
    last_run_status: str | None
    type: str
    is_configurable: bool
    # First run time only, for installed iOS builds that know just one.
    schedule: ScheduleTime | None = None
    schedule_times: list[ScheduleTime] | None = None
    schedule_timezone: str | None = None
    max_schedule_times: int | None = None
    interval_minutes: int | None = None
    last_run_failed_steps: list[str] | None = None


class JobsStatusResponse(BaseModel):
    jobs: list[JobStatus]


# Bounds on ``GET /jobs/runs?limit=``.
RUN_HISTORY_DEFAULT_LIMIT = 20
RUN_HISTORY_MAX_LIMIT = 100


class JobRun(BaseModel):
    """One recorded job run: a SyncLog row (issues #246, #242).

    ``job_type`` is ``playlist_update``, ``library_sync``, ``cleanup`` or
    ``manual_playlist_update``. ``status`` is ``running``, ``success`` or
    ``failed``; ``failure_code`` says why a run failed (``interrupted`` for
    one the process died under, ``credentials_unreadable`` when the user
    has to sign in again). ``message`` and ``results`` are only set on a
    finished manual run: the message and per-playlist outcomes the
    synchronous run endpoints return.
    """

    id: int
    job_type: str
    status: str
    details: str | None
    failure_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    playlists_attempted: int | None
    playlists_failed: int | None
    api_calls_used: int | None
    message: str | None = None
    results: list[RunAllPlaylistResult] | None = None


class JobRunListResponse(BaseModel):
    runs: list[JobRun]


def _job_run(row: SyncLog) -> JobRun:
    outcome = row.outcome if isinstance(row.outcome, dict) else {}
    return JobRun(
        id=row.id,
        job_type=row.job_type,
        status=row.status.value,
        details=row.details,
        failure_code=row.failure_code,
        started_at=row.started_at,
        completed_at=row.completed_at,
        playlists_attempted=row.playlists_attempted,
        playlists_failed=row.playlists_failed,
        api_calls_used=row.api_calls_used,
        message=outcome.get("message"),
        results=outcome.get("results"),
    )


@router.get("/runs", response_model=JobRunListResponse)
async def list_job_runs(
    job_type: Annotated[str | None, Query(max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=RUN_HISTORY_MAX_LIMIT)] = RUN_HISTORY_DEFAULT_LIMIT,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JobRunListResponse:
    """Recent job runs, newest first, optionally of one ``job_type`` (issue #246).

    SyncLog has no owner column: the deployment is single-user by
    construction (see CLAUDE.md), like the podcasts table.
    """
    query = select(SyncLog).order_by(SyncLog.started_at.desc(), SyncLog.id.desc()).limit(limit)
    if job_type:
        query = query.where(SyncLog.job_type == job_type)
    rows = (await db.execute(query)).scalars().all()
    return JobRunListResponse(runs=[_job_run(row) for row in rows])


@router.get("/runs/{run_id}", response_model=JobRun)
async def get_job_run(
    run_id: Annotated[int, Path(ge=1, le=DB_ID_MAX)],
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JobRun:
    """One job run, for polling an async manual run until it finishes (issue #242)."""
    row = await db.get(SyncLog, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _job_run(row)


class UpdateScheduleResponse(BaseModel):
    message: str
    next_run: str


@router.get("/status", response_model=JobsStatusResponse, response_model_exclude_unset=True)
async def jobs_status(user_id: int = Depends(get_current_user_id)) -> dict:
    """Get scheduler job statuses."""
    return {"jobs": await get_job_status()}


class UpdateScheduleRequest(BaseModel):
    """Either ``times`` (1 to MAX_PLAYLIST_UPDATE_TIMES run times) or the
    single ``hour`` + ``minute`` that installed iOS builds still send.
    ``times`` wins when both are present."""

    times: list[ScheduleTime] | None = Field(default=None, min_length=1, max_length=MAX_PLAYLIST_UPDATE_TIMES)
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)

    @model_validator(mode="after")
    def _one_form(self) -> "UpdateScheduleRequest":
        if self.times is None and (self.hour is None or self.minute is None):
            raise ValueError("Send either times, or hour and minute")
        return self

    def as_tuples(self) -> list[tuple[int, int]]:
        if self.times is not None:
            return [(t.hour, t.minute) for t in self.times]
        return [(self.hour, self.minute)]


@router.put("/schedule", response_model=UpdateScheduleResponse)
@limiter.limit("10/hour")
async def update_schedule(
    request: Request,
    schedule: UpdateScheduleRequest,
    session: Session = Depends(validate_csrf_token),
) -> dict:
    """Update when the library sync + playlist update runs (1 to 3 times a day).

    State-changing, so it goes through ``validate_csrf_token`` like every
    other mutating endpoint — it previously only checked the session cookie
    (issue #147).
    """
    next_run = await reschedule_playlist_update(schedule.as_tuples())
    if next_run is None:
        # The job exists but has no next run — it was paused rather than
        # rescheduled. Rescheduling failures raise instead of returning None.
        raise HTTPException(status_code=500, detail="Schedule updated but no next run is scheduled")
    return {"message": "Schedule updated", "next_run": next_run}
