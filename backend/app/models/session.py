"""Session model for database-backed session storage."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base
from app.models.types import UTCDateTime


class Session(Base):
    """Database-backed session storage with expiration tracking.

    Only the SHA-256 of the session ID is stored (``session_id_hash``), so a
    copy of the database or a backup can't be replayed as a login. The
    plaintext ID exists only in the client's cookie (or the iOS Keychain);
    ``SessionService`` hashes it for every lookup.

    The column keeps its old name, ``session_id``: renaming it would make an
    older image rolled back onto a migrated database fail on every
    authenticated request, where keeping it just signs everyone out.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id_hash: Mapped[str] = mapped_column("session_id", String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    last_accessed_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<Session(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"
