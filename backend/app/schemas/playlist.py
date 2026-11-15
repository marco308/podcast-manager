"""Playlist Pydantic schemas."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.models.playlist import ALL_EPISODES, Arrangement, DateDirection, PickFrom, PlaylistKind
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
# Largest value SQLite's INTEGER can hold. A bigger int reaches the driver
# and raises OverflowError (a 500) instead of simply matching no row.
DB_ID_MAX = 2**63 - 1
# A row ID taken from a request body.
DbId = Annotated[int, Field(ge=1, le=DB_ID_MAX)]
# ``episode_limit`` is 0 (all) or 1..N; N is bounded by the per-show fetch cap.
EPISODE_LIMIT_MAX = 500


def _blank_id_is_none(value: object) -> object:
    """A blank field means "no link", not an empty ID."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# A Spotify playlist to link, or None for no link.
SpotifyPlaylistLink = Annotated[
    Annotated[str, Field(max_length=SPOTIFY_ID_MAX_LENGTH, pattern=SPOTIFY_ID_PATTERN)] | None,
    BeforeValidator(_blank_id_is_none),
]


class PlaylistBase(BaseModel):
    """Base playlist schema."""

    name: str
    is_enabled: bool = True
    # ``sleep`` plays episodes already heard (issue #331).
    kind: PlaylistKind = PlaylistKind.STANDARD
    # Defaults inherited by assignments without an override.
    default_episode_limit: int = Field(ALL_EPISODES, ge=0, le=EPISODE_LIMIT_MAX)
    default_pick_from: PickFrom = PickFrom.NEWEST
    # Assembly.
    arrangement: Arrangement = Arrangement.BY_POSITION
    date_direction: DateDirection = DateDirection.OLDEST_FIRST


class PlaylistCreate(PlaylistBase):
    """Schema for creating a playlist."""

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    spotify_playlist_id: SpotifyPlaylistLink = None


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
    spotify_playlist_id: SpotifyPlaylistLink = None

    is_enabled: bool | None = None
    kind: PlaylistKind | None = None
    default_episode_limit: int | None = Field(None, ge=0, le=EPISODE_LIMIT_MAX)
    default_pick_from: PickFrom | None = None
    arrangement: Arrangement | None = None
    date_direction: DateDirection | None = None

    @model_validator(mode="after")
    def _no_explicit_nulls(self) -> "PlaylistUpdate":
        """Refuse ``null`` on a field a playlist can't be without (issue #310).

        ``None`` is the default so that an absent field means "leave it
        alone", but a field sent as ``null`` used to be read the same way and
        the client got a 200 for a no-op. Only ``spotify_playlist_id`` gives
        ``null`` a meaning (unlink). Neither client sends ``null`` for the
        others: iOS encodes them from non-optional values, and the web form
        can only clear the Spotify link.
        """
        nulled = sorted(
            field
            for field in self.model_fields_set
            if field not in PLAYLIST_UPDATE_NULLABLE and getattr(self, field) is None
        )
        if nulled:
            raise ValueError(f"{', '.join(nulled)} cannot be null; leave the field out to keep its current value")
        return self


# Fields of ``PlaylistUpdate`` where a present ``null`` means something.
PLAYLIST_UPDATE_NULLABLE = frozenset({"spotify_playlist_id"})


class RunPlaylistResponse(BaseModel):
    """``POST /playlists/{id}/run``.

    ``skipped`` and ``partial`` are only sent when true (the route is served
    with ``response_model_exclude_unset``), as before the model existed.
    """

    message: str
    playlist_id: int
    episode_count: int
    # A disabled playlist was left untouched.
    skipped: bool | None = None
    # The playlist was written, but from incomplete data.
    partial: bool | None = None


class RunAllPlaylistResult(BaseModel):
    """One playlist's outcome in ``POST /playlists/run-all``."""

    playlist_id: int
    playlist_name: str
    success: bool
    episode_count: int
    error: str | None
    partial: bool
    skipped: bool


class RunAllPlaylistsResponse(BaseModel):
    """``POST /playlists/run-all``."""

    message: str
    results: list[RunAllPlaylistResult]


class AddPodcastsResponse(BaseModel):
    """``POST /playlists/{id}/podcasts``."""

    message: str
    added: int


class PlaylistListResponse(BaseModel):
    """Schema for playlist list."""

    items: list[PlaylistResponse]
    total: int


class PlaylistPodcastAdd(BaseModel):
    """Schema for adding podcasts to a playlist."""

    podcast_ids: list[DbId] = Field(max_length=PODCAST_IDS_MAX_LENGTH)


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
    unplayed_counted_at: datetime | None = None
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
    """Schema for reordering podcasts within a playlist.

    Must list every assigned podcast exactly once — the router refuses a
    partial or repeated list, which would leave two rows on one position.
    """

    podcast_ids: list[DbId] = Field(max_length=PODCAST_IDS_MAX_LENGTH)


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
    # True when the listing stopped at the page cap with more playlists left
    # on Spotify, so the picker can say the list is incomplete.
    truncated: bool = False
