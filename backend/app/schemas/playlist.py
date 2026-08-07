"""Playlist Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.playlist import EpisodeMode, PlaylistOrderingMode

# Spotify playlist IDs are 22 chars of base62 — 64 leaves slack without
# accepting arbitrary-length input.
SPOTIFY_ID_MAX_LENGTH = 64
# The name column is String(255); reject anything longer at the edge.
NAME_MAX_LENGTH = 255
# Sanity cap on bulk assignment/reorder payloads.
PODCAST_IDS_MAX_LENGTH = 500


class PlaylistBase(BaseModel):
    """Base playlist schema."""

    name: str
    episode_mode: EpisodeMode = EpisodeMode.ALL_UNPLAYED
    is_enabled: bool = True
    is_weekend_only: bool = False
    ordering_mode: PlaylistOrderingMode = PlaylistOrderingMode.DEFAULT


class PlaylistCreate(PlaylistBase):
    """Schema for creating a playlist."""

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    spotify_playlist_id: str | None = Field(None, max_length=SPOTIFY_ID_MAX_LENGTH)


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

    name: str | None = Field(None, min_length=1, max_length=NAME_MAX_LENGTH)
    spotify_playlist_id: str | None = Field(None, max_length=SPOTIFY_ID_MAX_LENGTH)
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

    podcast_ids: list[int] = Field(max_length=PODCAST_IDS_MAX_LENGTH)


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


class PlaylistPodcastListResponse(BaseModel):
    """Schema for list of podcasts within a playlist."""

    items: list[PlaylistPodcastResponse]
    total: int


class PlaylistPodcastReorder(BaseModel):
    """Schema for reordering podcasts within a playlist."""

    podcast_ids: list[int] = Field(max_length=PODCAST_IDS_MAX_LENGTH)
