"""Podcast Pydantic schemas."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


class PodcastCategory(str, Enum):
    """Podcast category types."""

    PRIMARY = "primary"
    NEWS = "news"
    BACKGROUND = "background"
    WEEKEND = "weekend"


class PodcastBase(BaseModel):
    """Base podcast schema."""

    spotify_id: str
    name: str
    description: str | None = None
    image_url: str | None = None
    publisher: str | None = None
    total_episodes: int = 0
    unplayed_episodes: int = 0


class PodcastResponse(PodcastBase):
    """Schema for podcast API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    categories: list[PodcastCategory]
    is_sequential: bool
    is_weekend_only: bool
    morning_order: int | None  # DEPRECATED: use playlist_order
    playlist_order: int | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PodcastUpdate(BaseModel):
    """Schema for updating podcast metadata."""

    categories: list[PodcastCategory] | None = None
    is_sequential: bool | None = None
    is_weekend_only: bool | None = None
    morning_order: int | None = None  # DEPRECATED: use playlist_order
    playlist_order: int | None = None

    @field_validator("categories")
    @classmethod
    def deduplicate_categories(cls, v: list[PodcastCategory] | None) -> list[PodcastCategory] | None:
        if v is not None:
            return list(dict.fromkeys(v))
        return v


class PodcastListResponse(BaseModel):
    """Schema for paginated podcast list."""

    items: list[PodcastResponse]
    total: int
