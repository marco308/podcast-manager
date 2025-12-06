"""Podcast Pydantic schemas."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class PodcastCategory(str, Enum):
    """Podcast category types."""

    PRIMARY = "primary"
    NEWS = "news"
    BACKGROUND = "background"
    NONE = "none"


class PodcastBase(BaseModel):
    """Base podcast schema."""

    spotify_id: str
    name: str
    description: str | None = None
    image_url: str | None = None
    publisher: str | None = None
    total_episodes: int = 0


class PodcastResponse(PodcastBase):
    """Schema for podcast API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    category: PodcastCategory
    is_sequential: bool
    is_weekend_only: bool
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PodcastUpdate(BaseModel):
    """Schema for updating podcast metadata."""

    category: PodcastCategory | None = None
    is_sequential: bool | None = None
    is_weekend_only: bool | None = None


class PodcastListResponse(BaseModel):
    """Schema for paginated podcast list."""

    items: list[PodcastResponse]
    total: int
