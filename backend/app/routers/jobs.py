"""Jobs API router."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.jobs.scheduler import get_job_status, reschedule_playlist_update
from app.models.session import Session
from app.rate_limit import limiter
from app.routers.auth import get_current_user_id, validate_csrf_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/status")
async def jobs_status(user_id: int = Depends(get_current_user_id)) -> dict:
    """Get scheduler job statuses."""
    return {"jobs": await get_job_status()}


class UpdateScheduleRequest(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)


@router.put("/schedule")
@limiter.limit("10/hour")
async def update_schedule(
    request: Request,
    schedule: UpdateScheduleRequest,
    session: Session = Depends(validate_csrf_token),
) -> dict:
    """Update the daily playlist update schedule.

    State-changing, so it goes through ``validate_csrf_token`` like every
    other mutating endpoint — it previously only checked the session cookie
    (issue #147).
    """
    next_run = await reschedule_playlist_update(schedule.hour, schedule.minute)
    if next_run is None:
        # The job exists but has no next run — it was paused rather than
        # rescheduled. Rescheduling failures raise instead of returning None.
        raise HTTPException(status_code=500, detail="Schedule updated but no next run is scheduled")
    return {"message": "Schedule updated", "next_run": next_run}
