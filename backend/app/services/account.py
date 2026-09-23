"""Deleting a user's account and data (issue #266).

App Store Guideline 5.1.1(v) requires an app that creates accounts to let
people delete them from inside the app. Signing in with Spotify creates a
``User`` row (profile, encrypted tokens), so both clients offer this.

Every table is deleted explicitly rather than through ``ondelete="CASCADE"``:
SQLite only enforces foreign keys with ``PRAGMA foreign_keys=ON``, which
``database.py`` doesn't set, so the declared cascades never fire.

Spotify itself is left alone. Playlists the app created stay in the user's
Spotify library, and Spotify has no token-revocation endpoint; access is
removed at spotify.com/account/apps.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Playlist, PlaylistPodcast, Podcast, Session, SyncLog, User


@dataclass(frozen=True)
class AccountDeletionResult:
    playlists: int
    podcasts: int
    sessions: int


async def delete_account(db: AsyncSession, user_id: int) -> AccountDeletionResult:
    """Delete the user and everything stored for them. Does not commit.

    ``podcasts`` and ``sync_logs`` have no ``user_id`` — they are global by
    design, because the deployment is single-user (issue #154). They are
    wiped only when no other user remains, so a deployment that predates the
    registration lock never loses another user's library.

    ``app_settings`` is server configuration (the job schedule), not user
    data, and survives.
    """
    playlist_ids = select(Playlist.id).where(Playlist.user_id == user_id)
    await db.execute(delete(PlaylistPodcast).where(PlaylistPodcast.playlist_id.in_(playlist_ids)))
    playlists = await db.execute(delete(Playlist).where(Playlist.user_id == user_id))
    sessions = await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))

    remaining = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    podcast_count = 0
    if remaining == 0:
        # The assignments of any other user's playlists are gone with them,
        # but clear stragglers first so no row points at a deleted podcast.
        await db.execute(delete(PlaylistPodcast))
        podcast_count = (await db.execute(delete(Podcast))).rowcount or 0
        await db.execute(delete(SyncLog))

    await db.flush()
    return AccountDeletionResult(
        playlists=playlists.rowcount or 0,
        podcasts=podcast_count,
        sessions=sessions.rowcount or 0,
    )
