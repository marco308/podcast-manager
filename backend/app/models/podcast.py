"""Podcast model for storing podcast metadata and categorization."""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class PodcastCategory(str, PyEnum):
    """Podcast category types."""

    PRIMARY = "primary"
    NEWS = "news"
    BACKGROUND = "background"
    WEEKEND = "weekend"


class Podcast(Base):
    """Podcast model storing metadata and custom categorization."""

    __tablename__ = "podcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spotify_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_episodes: Mapped[int] = mapped_column(Integer, default=0)
    unplayed_episodes: Mapped[int] = mapped_column(Integer, default=0)

    # Custom categorization fields
    categories: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        server_default="[]",
    )
    is_sequential: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_weekend_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    morning_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # DEPRECATED: use playlist_order
    playlist_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Sync tracking
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def has_category(self, category: PodcastCategory) -> bool:
        """Check if this podcast belongs to the given category."""
        return category.value in (self.categories or [])

    def __repr__(self) -> str:
        return f"<Podcast(id={self.id}, name={self.name}, categories={self.categories})>"
