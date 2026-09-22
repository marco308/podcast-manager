"""Podcast model for storing podcast metadata."""

from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.types import UTCDateTime


class Podcast(Base):
    """Podcast model storing metadata."""

    __tablename__ = "podcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spotify_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_episodes: Mapped[int] = mapped_column(Integer, default=0)
    # NULL = not counted yet. Only the playlist build writes it, and only after
    # reading the show's whole catalogue (issue #155).
    unplayed_episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Podcast attributes
    is_sequential: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Sync tracking
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    playlist_assignments = relationship("PlaylistPodcast", back_populates="podcast", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Podcast(id={self.id}, name={self.name})>"
