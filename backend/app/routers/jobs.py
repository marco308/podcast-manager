"""Jobs API router."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.jobs.scheduler import get_job_status, reschedule_playlist_update
from app.routers.auth import get_current_user_id

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
async def update_schedule(
    request: UpdateScheduleRequest,
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Update the daily playlist update schedule."""
    next_run = await reschedule_playlist_update(request.hour, request.minute)
    if next_run is None:
        raise HTTPException(status_code=500, detail="Failed to update schedule")
    return {"message": "Schedule updated", "next_run": next_run}
