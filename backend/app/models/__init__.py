"""SQLAlchemy ORM Models.

Import ``Base`` from here rather than ``app.database`` when you need
``Base.metadata`` to hold every table: importing this package registers them all.
"""

from app.database import Base
from app.models.playlist import ALL_EPISODES, Arrangement, DateDirection, PickFrom, Playlist
from app.models.playlist_podcast import PlaylistPodcast
from app.models.podcast import Podcast
from app.models.session import Session
from app.models.settings import AppSetting
from app.models.sync_log import SyncLog
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "Podcast",
    "Playlist",
    "PlaylistPodcast",
    "ALL_EPISODES",
    "Arrangement",
    "DateDirection",
    "PickFrom",
    "SyncLog",
    "Session",
    "AppSetting",
]
