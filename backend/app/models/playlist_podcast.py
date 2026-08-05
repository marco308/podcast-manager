"""PlaylistPodcast join table model for direct playlist-podcast assignments."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class PlaylistPodcast(Base):
    """Join table for many-to-many playlist-podcast assignments."""

    __tablename__ = "playlist_podcasts"
    __table_args__ = (UniqueConstraint("playlist_id", "podcast_id", name="uq_playlist_podcast"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playlist_id: Mapped[int] = mapped_column(Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False)
    podcast_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("podcasts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    playlist = relationship("Playlist", back_populates="podcast_assignments")
    podcast = relationship("Podcast", back_populates="playlist_assignments")

    def __repr__(self) -> str:
        return (
            f"<PlaylistPodcast(playlist_id={self.playlist_id}, podcast_id={self.podcast_id}, position={self.position})>"
        )
