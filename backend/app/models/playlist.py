"""Playlist model for storing managed playlist configurations."""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.types import UTCDateTime

# ``episode_limit`` encoding, shared by the playlist default and the
# per-assignment override: 0 means "all unplayed", n >= 1 means "at most n".
# Using the same encoding at both levels leaves NULL free to mean "inherit"
# on the assignment (docs/design/assignment-rules.md).
ALL_EPISODES = 0


class PickFrom(str, PyEnum):
    """Which end of a show's unplayed episodes to take from.

    Also the order the show's episodes are listened to. ``OLDEST`` is what a
    serial wants ("next unfinished"); ``NEWEST`` is what daily news wants.
    """

    NEWEST = "newest"
    OLDEST = "oldest"


class Arrangement(str, PyEnum):
    """How the contributions of each assigned show are assembled."""

    BY_POSITION = "by_position"  # groups in assignment order
    BY_DATE = "by_date"  # everything merged by release date
    SHUFFLE = "shuffle"  # shows interleaved at random, each show kept in order


class DateDirection(str, PyEnum):
    """Direction of the merge when ``arrangement`` is ``BY_DATE``."""

    NEWEST_FIRST = "newest_first"
    OLDEST_FIRST = "oldest_first"


class Playlist(Base):
    """Playlist model storing configuration for managed playlists.

    The playlist owns the *defaults* for its assignments and the *assembly*
    rules. What each show contributes is decided per assignment — see
    ``PlaylistPodcast`` and ``services/assignment_rules.py``.
    """

    __tablename__ = "playlists"
    # Two playlists linked to one Spotify playlist would overwrite each other
    # on every rebuild. The API refuses it up front; this is what makes the
    # refusal race-proof (issue #245). NULL repeats freely — SQLite and
    # Postgres both treat NULLs as distinct — so unlinked playlists are fine.
    __table_args__ = (UniqueConstraint("user_id", "spotify_playlist_id", name="uq_playlists_user_spotify_playlist"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    spotify_playlist_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Defaults inherited by assignments that have no override.
    default_episode_limit: Mapped[int] = mapped_column(Integer, default=ALL_EPISODES, nullable=False)
    default_pick_from: Mapped[str] = mapped_column(String(10), default=PickFrom.NEWEST.value, nullable=False)

    # Assembly.
    arrangement: Mapped[str] = mapped_column(String(20), default=Arrangement.BY_POSITION.value, nullable=False)
    date_direction: Mapped[str] = mapped_column(String(20), default=DateDirection.OLDEST_FIRST.value, nullable=False)

    # Tracking
    last_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)

    # Relationships
    podcast_assignments = relationship("PlaylistPodcast", back_populates="playlist", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Playlist(id={self.id}, name={self.name}, arrangement={self.arrangement})>"
