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
    unplayed_episodes: int | None = None
    # When unplayed_episodes was counted (issue #241); NULL = not counted.
    unplayed_counted_at: datetime | None = None


class PodcastResponse(PodcastBase):
    """Schema for podcast API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_sequential: bool
    is_archived: bool = False
    playlist_ids: list[int] = []
    last_synced_at: datetime | None
    # First sync that found the show gone from the Spotify library (issue
    # #155). The show contributes no episodes to a build while it is set, and
    # the row is deleted once it has been missing for UNSUBSCRIBE_GRACE.
    missing_since: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PodcastUpdate(BaseModel):
    """Schema for updating podcast metadata."""

    is_sequential: bool | None = None
    is_archived: bool | None = None


class PodcastListResponse(BaseModel):
    """Schema for paginated podcast list."""

    items: list[PodcastResponse]
    total: int
