"""Playlist model for storing managed playlist configurations."""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Enum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class PlaylistRuleType(str, PyEnum):
    """Playlist rule types."""

    PRIMARY = "primary"
    NEWS = "news"
    MORNING = "morning"
    BACKGROUND = "background"


class Playlist(Base):
    """Playlist model storing configuration for managed playlists."""

    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    spotify_playlist_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rule_type: Mapped[PlaylistRuleType] = mapped_column(
        Enum(PlaylistRuleType), nullable=False
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Tracking
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Playlist(id={self.id}, name={self.name}, rule_type={self.rule_type})>"
