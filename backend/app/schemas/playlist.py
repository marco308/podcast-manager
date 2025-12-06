"""Playlist Pydantic schemas."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class PlaylistRuleType(str, Enum):
    """Playlist rule types."""

    PRIMARY = "primary"
    NEWS = "news"
    MORNING = "morning"
    BACKGROUND = "background"


class PlaylistBase(BaseModel):
    """Base playlist schema."""

    name: str
    rule_type: PlaylistRuleType
    is_enabled: bool = True


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


class PlaylistUpdate(BaseModel):
    """Schema for updating playlist configuration."""

    name: str | None = None
    spotify_playlist_id: str | None = None
    is_enabled: bool | None = None


class PlaylistListResponse(BaseModel):
    """Schema for playlist list."""

    items: list[PlaylistResponse]
    total: int
