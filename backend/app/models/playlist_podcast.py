"""PlaylistPodcast join table model for direct playlist-podcast assignments."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.types import UTCDateTime


class PlaylistPodcast(Base):
    """Join table for many-to-many playlist-podcast assignments.

    The assignment is where "what this show contributes to this playlist"
    lives. ``episode_limit`` and ``pick_from`` are *overrides*: NULL means
    inherit from the playlist (and, for ``pick_from``, from the podcast's
    ``is_sequential`` hint). See docs/design/assignment-rules.md.
    """

    __tablename__ = "playlist_podcasts"
    __table_args__ = (UniqueConstraint("playlist_id", "podcast_id", name="uq_playlist_podcast"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playlist_id: Mapped[int] = mapped_column(Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False)
    podcast_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("podcasts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0 = all unplayed, n >= 1 = at most n, NULL = inherit the playlist default.
    episode_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "newest" / "oldest", NULL = inherit (sequential hint, then playlist default).
    pick_from: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)

    # Relationships
    playlist = relationship("Playlist", back_populates="podcast_assignments")
    podcast = relationship("Podcast", back_populates="playlist_assignments")

    def __repr__(self) -> str:
        return (
            f"<PlaylistPodcast(playlist_id={self.playlist_id}, podcast_id={self.podcast_id}, "
            f"position={self.position}, episode_limit={self.episode_limit}, pick_from={self.pick_from})>"
        )
