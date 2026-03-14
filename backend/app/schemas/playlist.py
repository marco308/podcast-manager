"""Playlist Pydantic schemas."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class EpisodeMode(str, Enum):
    """Episode selection mode."""

    ALL_UNPLAYED = "all_unplayed"
    LATEST_ONLY = "latest_only"


class PlaylistOrderingMode(str, Enum):
    """Playlist ordering modes."""

    DEFAULT = "default"
    PODCAST_ORDER = "podcast_order"
    CHRONOLOGICAL_ASC = "chronological_asc"
    CHRONOLOGICAL_DESC = "chronological_desc"


class PlaylistBase(BaseModel):
    """Base playlist schema."""

    name: str
    episode_mode: EpisodeMode = EpisodeMode.ALL_UNPLAYED
    is_enabled: bool = True
    is_weekend_only: bool = False
    ordering_mode: PlaylistOrderingMode = PlaylistOrderingMode.DEFAULT


class PlaylistCreate(PlaylistBase):
    """Schema for creating a playlist."""

    spotify_playlist_id: str | None = None


class PlaylistResponse(PlaylistBase):
    """Schema for playlist API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    spotify_playlist_id: str | None
    last_updated_at: datetime | None
    created_at: datetime
    podcast_count: int = 0


class PlaylistUpdate(BaseModel):
    """Schema for updating playlist configuration."""

    name: str | None = None
    spotify_playlist_id: str | None = None
    is_enabled: bool | None = None
    episode_mode: EpisodeMode | None = None
    is_weekend_only: bool | None = None
    ordering_mode: PlaylistOrderingMode | None = None


class PlaylistListResponse(BaseModel):
    """Schema for playlist list."""

    items: list[PlaylistResponse]
    total: int


class PlaylistPodcastAdd(BaseModel):
    """Schema for adding podcasts to a playlist."""

    podcast_ids: list[int]


class PlaylistPodcastResponse(BaseModel):
    """Schema for a podcast within a playlist."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    spotify_id: str
    name: str
    description: str | None = None
    image_url: str | None = None
    publisher: str | None = None
    total_episodes: int = 0
    unplayed_episodes: int = 0
    is_sequential: bool
    position: int | None = None


class PlaylistPodcastReorder(BaseModel):
    """Schema for reordering podcasts within a playlist."""

    podcast_ids: list[int]
