"""Playlist Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.playlist import ALL_EPISODES, Arrangement, DateDirection, PickFrom
from app.services.assignment_rules import RuleSource

# Spotify playlist IDs are 22 chars of base62 — 64 leaves slack without
# accepting arbitrary-length input.
SPOTIFY_ID_MAX_LENGTH = 64
# Base62 only: the ID is interpolated into a Spotify URL path.
SPOTIFY_ID_PATTERN = r"^[A-Za-z0-9]+$"
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
    # Defaults inherited by assignments without an override.
    default_episode_limit: int = Field(ALL_EPISODES, ge=0, le=EPISODE_LIMIT_MAX)
    default_pick_from: PickFrom = PickFrom.NEWEST
    # Assembly.
    arrangement: Arrangement = Arrangement.BY_POSITION
    date_direction: DateDirection = DateDirection.OLDEST_FIRST


class PlaylistCreate(PlaylistBase):
    """Schema for creating a playlist."""

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    spotify_playlist_id: str | None = Field(None, max_length=SPOTIFY_ID_MAX_LENGTH, pattern=SPOTIFY_ID_PATTERN)

    @field_validator("spotify_playlist_id", mode="before")
    @classmethod
    def _blank_id_is_none(cls, value: object) -> object:
        """A blank field means "no link", not an empty ID."""
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class PlaylistResponse(PlaylistBase):
    """Schema for playlist API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    spotify_playlist_id: str | None
    last_updated_at: datetime | None
    created_at: datetime
    podcast_count: int = 0
    # Always False: the setting was removed (issue #238), but installed iOS
    # builds decode it as a required field. Drop once they are gone.
    is_weekend_only: bool = False


class PlaylistUpdate(BaseModel):
    """Schema for updating playlist configuration."""

    name: str | None = Field(None, min_length=1, max_length=NAME_MAX_LENGTH)
    spotify_playlist_id: str | None = Field(None, max_length=SPOTIFY_ID_MAX_LENGTH, pattern=SPOTIFY_ID_PATTERN)

    @field_validator("spotify_playlist_id", mode="before")
    @classmethod
    def _blank_id_is_none(cls, value: object) -> object:
        """A blank field means "no link", not an empty ID."""
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    is_enabled: bool | None = None
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
    unplayed_episodes: int | None = None
    is_sequential: bool
    # Gone from the Spotify library: the assignment is still here but the
    # show is skipped by the next build (issues #155, #240).
    missing_since: datetime | None = None
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


class SpotifyPlaylistOption(BaseModel):
    """A Spotify playlist the user owns, offered as a link target (issue #245)."""

    id: str
    name: str
    image_url: str | None = None
    item_count: int = 0
    # The managed playlist already linked to it, if any — linking it again
    # would have two playlists overwrite each other.
    linked_playlist_id: int | None = None


class SpotifyPlaylistOptionListResponse(BaseModel):
    """Owned Spotify playlists available to link."""

    items: list[SpotifyPlaylistOption]
    total: int
