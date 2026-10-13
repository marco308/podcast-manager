"""Ledger of episodes a sleep playlist has served (issue #331)."""

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.types import UTCDateTime


class SleepEpisode(Base):
    """An episode a sleep build has written to Spotify.

    Falling asleep to a finished episode moves its resume point, and Spotify
    then reports it as partially played. Without this ledger the episode
    would drop out of the next sleep build and come back to every standard
    playlist as unplayed. So: sleep builds treat these as heard, and standard
    builds skip them, whatever Spotify says now. Only episodes Sleep served
    are recorded, so marking any other episode unplayed still works.

    Global like ``podcasts`` (single-user by construction).
    """

    __tablename__ = "sleep_episodes"

    episode_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_served_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_served_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    def __repr__(self) -> str:
        return f"<SleepEpisode(episode_id={self.episode_id})>"
