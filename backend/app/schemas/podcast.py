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
    is_archived: bool = False
    playlist_ids: list[int] = []
    last_synced_at: datetime | None
    # Set when the last sync no longer found the show in the user's Spotify
    # library. The row and its assignments survive, but the show contributes
    # no episodes to a build until it is followed again (issue #240).
    unfollowed_at: datetime | None = None
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
