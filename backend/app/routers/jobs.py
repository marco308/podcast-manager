"""Jobs API router."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.jobs.scheduler import MAX_PLAYLIST_UPDATE_TIMES, get_job_status, reschedule_playlist_update
from app.models.session import Session
from app.rate_limit import limiter
from app.routers.auth import get_current_user_id, validate_csrf_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/status")
async def jobs_status(user_id: int = Depends(get_current_user_id)) -> dict:
    """Get scheduler job statuses."""
    return {"jobs": await get_job_status()}


class ScheduleTime(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)


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


@router.put("/schedule")
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
