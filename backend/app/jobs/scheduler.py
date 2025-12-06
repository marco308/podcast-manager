"""APScheduler setup and job management (Phase 3 stub)."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Global scheduler instance
scheduler = AsyncIOScheduler()


def init_scheduler() -> None:
    """Initialize and start the scheduler.

    Jobs will be added in Phase 3.
    """
    if not scheduler.running:
        scheduler.start()


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=True)


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
