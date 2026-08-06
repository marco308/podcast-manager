"""Playlist model for storing managed playlist configurations."""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.types import UTCDateTime


class EpisodeMode(str, PyEnum):
    """Episode selection mode for playlists."""

    ALL_UNPLAYED = "all_unplayed"
    LATEST_ONLY = "latest_only"


class PlaylistOrderingMode(str, PyEnum):
    """Playlist ordering modes."""

    DEFAULT = "default"  # Use default logic (backward compatible)
    PODCAST_ORDER = "podcast_order"  # Order by position in join table
    CHRONOLOGICAL_ASC = "chronological_asc"  # Oldest episodes first
    CHRONOLOGICAL_DESC = "chronological_desc"  # Newest episodes first


class Playlist(Base):
    """Playlist model storing configuration for managed playlists."""

    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    spotify_playlist_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    episode_mode: Mapped[str] = mapped_column(String(20), default="all_unplayed", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_weekend_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ordering_mode: Mapped[PlaylistOrderingMode] = mapped_column(
        Enum(PlaylistOrderingMode),
        default=PlaylistOrderingMode.DEFAULT,
        nullable=False,
    )

    # Tracking
    last_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)

    # Relationships
    podcast_assignments = relationship("PlaylistPodcast", back_populates="playlist", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Playlist(id={self.id}, name={self.name}, episode_mode={self.episode_mode})>"
