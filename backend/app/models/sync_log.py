"""SyncLog model for tracking background job executions."""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.types import UTCDateTime


class SyncStatus(str, PyEnum):
    """Sync job status.

    Jobs write ``RUNNING`` first and finalise to ``SUCCESS``/``FAILED``. There
    is no ``PENDING``: nothing ever queued a row before running it, so it was
    dropped (issue #248). The database enum type still carries ``pending``
    from migration 001; it is simply never written.
    """

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SyncLog(Base):
    """SyncLog model for debugging and monitoring background jobs."""

    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Failure classification (issue #89). All nullable so existing rows
    # written before migration 012 keep working untouched.
    failure_code: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    playlists_attempted: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    playlists_failed: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    api_calls_used: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    def __repr__(self) -> str:
        return f"<SyncLog(id={self.id}, job_type={self.job_type}, status={self.status})>"
