"""Playlist Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.playlist import ALL_EPISODES, Arrangement, DateDirection, PickFrom
from app.services.assignment_rules import RuleSource

# Spotify playlist IDs are 22 chars of base62 — 64 leaves slack without
# accepting arbitrary-length input.
SPOTIFY_ID_MAX_LENGTH = 64
# The name column is String(255); reject anything longer at the edge.
NAME_MAX_LENGTH = 255
# Sanity cap on bulk assignment/reorder payloads.
PODCAST_IDS_MAX_LENGTH = 500
# ``episode_limit`` is 0 (all) or 1..N; N is bounded by the per-show fetch cap.
EPISODE_LIMIT_MAX = 500


class PlaylistBase(BaseModel):
    """Base playlist schema."""

    name: str
    is_enabled: bool = True
    is_weekend_only: bool = False
    # Defaults inherited by assignments without an override.
    default_episode_limit: int = Field(ALL_EPISODES, ge=0, le=EPISODE_LIMIT_MAX)
    default_pick_from: PickFrom = PickFrom.NEWEST
    # Assembly.
    arrangement: Arrangement = Arrangement.BY_POSITION
    date_direction: DateDirection = DateDirection.OLDEST_FIRST


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
    is_weekend_only: bool | None = None
    default_episode_limit: int | None = Field(None, ge=0, le=EPISODE_LIMIT_MAX)
    default_pick_from: PickFrom | None = None
    arrangement: Arrangement | None = None
    date_direction: DateDirection | None = None


class PlaylistListResponse(BaseModel):
    """Schema for playlist list."""

    items: list[PlaylistResponse]
    total: int


class PlaylistPodcastAdd(BaseModel):
    """Schema for adding podcasts to a playlist."""

    podcast_ids: list[int] = Field(max_length=PODCAST_IDS_MAX_LENGTH)


class AssignmentRule(BaseModel):
    """The rule a build applies to one assignment, and where each part came from."""

    episode_limit: int
    pick_from: PickFrom
    episode_limit_source: RuleSource
    pick_from_source: RuleSource


class AssignmentOverride(BaseModel):
    """The raw per-assignment overrides. ``None`` means "inherit"."""

    episode_limit: int | None = None
    pick_from: PickFrom | None = None


class AssignmentOverrideUpdate(BaseModel):
    """Body for ``PATCH /playlists/{id}/podcasts/{podcast_id}``.

    A field that is present and ``null`` clears that override; a field that is
    absent is left alone (checked via ``model_fields_set``).
    """

    episode_limit: int | None = Field(None, ge=0, le=EPISODE_LIMIT_MAX)
    pick_from: PickFrom | None = None


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
    rule: AssignmentRule
    override: AssignmentOverride


class PlaylistPodcastListResponse(BaseModel):
    """Schema for list of podcasts within a playlist."""

    items: list[PlaylistPodcastResponse]
    total: int


class PlaylistPodcastReorder(BaseModel):
    """Schema for reordering podcasts within a playlist."""

    podcast_ids: list[int] = Field(max_length=PODCAST_IDS_MAX_LENGTH)
