"""Podcast Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    is_sequential: bool
    playlist_ids: list[int] = []
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PodcastUpdate(BaseModel):
    """Schema for updating podcast metadata."""

    is_sequential: bool | None = None


class PodcastListResponse(BaseModel):
    """Schema for paginated podcast list."""

    items: list[PodcastResponse]
    total: int
