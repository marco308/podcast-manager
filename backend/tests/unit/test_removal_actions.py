"""Tests for the split removal actions (issue #247).

- A podcast can be archived: hidden from lists and assignment, still followed
  on Spotify. Archiving drops its playlist assignments.
- Deleting a playlist can also remove (unfollow) it on Spotify; a Spotify
  failure leaves the local row in place.
- Renaming a playlist pushes the new name to Spotify; a Spotify failure saves
  nothing, a Spotify 404 still renames locally.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.routers.playlists as playlists_module
from app.database import Base
from app.jobs import locks
from app.models import Playlist, PlaylistPodcast, Podcast, User
from app.routers.playlists import add_podcasts_to_playlist, delete_playlist, update_playlist
from app.routers.podcasts import list_podcasts, update_podcast
from app.schemas.playlist import PlaylistPodcastAdd, PlaylistUpdate
from app.schemas.podcast import PodcastUpdate


@pytest.fixture(autouse=True)
def _fresh_lock():
    """Fresh write lock per test — asyncio primitives bind to the running loop."""
    original = locks.playlist_write_lock
    locks.playlist_write_lock = asyncio.Lock()
    try:
        yield
    finally:
        locks.playlist_write_lock = original


async def _make_db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    return engine, maker


def _user():
    return User(
        spotify_id="spotify-user",
        access_token="encrypted",
        refresh_token="encrypted",
        token_expires_at=datetime.now(UTC),
    )


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("DELETE", "https://api.spotify.com/v1/x")
    return httpx.HTTPStatusError("err", request=request, response=httpx.Response(status, request=request))


@pytest.fixture
def spotify(monkeypatch):
    """Stub the Spotify client and token manager the playlist router builds."""
    client = MagicMock()
    client.unfollow_playlist = AsyncMock()
    client.update_playlist_details = AsyncMock()
    monkeypatch.setattr(playlists_module, "SpotifyService", MagicMock(return_value=client))

    token_manager = MagicMock()
    token_manager.get_token = AsyncMock(return_value="token")
    token_manager.force_refresh = AsyncMock(return_value="token")
    monkeypatch.setattr(playlists_module, "TokenManager", MagicMock(return_value=token_manager))
    return client


SESSION = SimpleNamespace(user_id=1)


async def _list(db, **kwargs):
    params = {"include_archived": False, "limit": 50, "offset": 0}
    params.update(kwargs)
    return await list_podcasts(user_id=1, db=db, **params)


class TestArchivePodcast:
    @pytest.mark.asyncio
    async def test_archive_hides_podcast_and_drops_assignments(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Playlist"))
                db.add(Podcast(spotify_id="keep", name="Keep"))
                db.add(Podcast(spotify_id="hide", name="Hide"))
                await db.commit()
                db.add(PlaylistPodcast(playlist_id=1, podcast_id=2, position=1))
                await db.commit()

                # Routes are keyed by the integer id (issue #248).
                hide_id = (await db.execute(select(Podcast.id).where(Podcast.spotify_id == "hide"))).scalar_one()

                response = await update_podcast(
                    str(hide_id), PodcastUpdate(is_archived=True), session=SESSION, db=db
                )
                assert response.is_archived is True
                assert response.playlist_ids == []

                assignments = (await db.execute(select(func.count()).select_from(PlaylistPodcast))).scalar()
                assert assignments == 0

                listed = await _list(db)
                assert [p.spotify_id for p in listed.items] == ["keep"]
                assert listed.total == 1

                everything = await _list(db, include_archived=True)
                assert {p.spotify_id for p in everything.items} == {"keep", "hide"}

                # Unarchiving brings it back.
                await update_podcast(str(hide_id), PodcastUpdate(is_archived=False), session=SESSION, db=db)
                assert (await _list(db)).total == 2
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_archived_podcast_cannot_be_assigned(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Playlist"))
                db.add(Podcast(spotify_id="hide", name="Hide", is_archived=True))
                await db.commit()

                result = await add_podcasts_to_playlist(
                    playlist_id=1, data=PlaylistPodcastAdd(podcast_ids=[1]), session=SESSION, db=db
                )
                assert result["added"] == 0
        finally:
            await engine.dispose()


class TestDeletePlaylist:
    @pytest.mark.asyncio
    async def test_default_delete_leaves_spotify_alone(self, spotify):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="P", spotify_playlist_id="sp1"))
                await db.commit()

                await delete_playlist(1, remove_from_spotify=False, session=SESSION, db=db)

                spotify.unfollow_playlist.assert_not_called()
                assert (await db.execute(select(Playlist))).scalar_one_or_none() is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_remove_from_spotify_unfollows_then_deletes(self, spotify):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="P", spotify_playlist_id="sp1"))
                await db.commit()

                await delete_playlist(1, remove_from_spotify=True, session=SESSION, db=db)

                spotify.unfollow_playlist.assert_awaited_once()
                assert spotify.unfollow_playlist.await_args.args == ("sp1",)
                assert (await db.execute(select(Playlist))).scalar_one_or_none() is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_spotify_failure_keeps_local_row(self, spotify):
        spotify.unfollow_playlist.side_effect = _status_error(500)
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="P", spotify_playlist_id="sp1"))
                await db.commit()

                with pytest.raises(HTTPException) as exc_info:
                    await delete_playlist(1, remove_from_spotify=True, session=SESSION, db=db)
                assert exc_info.value.status_code == 502
                assert (await db.execute(select(Playlist))).scalar_one_or_none() is not None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_already_gone_on_spotify_still_deletes(self, spotify):
        spotify.unfollow_playlist.side_effect = _status_error(404)
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="P", spotify_playlist_id="sp1"))
                await db.commit()

                await delete_playlist(1, remove_from_spotify=True, session=SESSION, db=db)
                assert (await db.execute(select(Playlist))).scalar_one_or_none() is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_never_created_playlist_skips_spotify(self, spotify):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="P"))
                await db.commit()

                await delete_playlist(1, remove_from_spotify=True, session=SESSION, db=db)
                spotify.unfollow_playlist.assert_not_called()
                assert (await db.execute(select(Playlist))).scalar_one_or_none() is None
        finally:
            await engine.dispose()


class TestRenamePlaylist:
    @pytest.mark.asyncio
    async def test_rename_pushes_name_to_spotify(self, spotify):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Old", spotify_playlist_id="sp1"))
                await db.commit()

                response = await update_playlist(1, PlaylistUpdate(name="New"), session=SESSION, db=db)

                assert response.name == "New"
                spotify.update_playlist_details.assert_awaited_once()
                call = spotify.update_playlist_details.await_args
                assert call.args == ("sp1",)
                assert call.kwargs["name"] == "New"
                assert "New" in call.kwargs["description"]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_unchanged_name_or_no_spotify_playlist_skips_spotify(self, spotify):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Same", spotify_playlist_id="sp1"))
                db.add(Playlist(user_id=1, name="Local"))
                await db.commit()

                await update_playlist(1, PlaylistUpdate(name="Same", is_enabled=False), session=SESSION, db=db)
                response = await update_playlist(2, PlaylistUpdate(name="Renamed"), session=SESSION, db=db)

                assert response.name == "Renamed"
                spotify.update_playlist_details.assert_not_called()
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_spotify_failure_saves_nothing(self, spotify):
        spotify.update_playlist_details.side_effect = _status_error(500)
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Old", spotify_playlist_id="sp1"))
                await db.commit()

                with pytest.raises(HTTPException) as exc_info:
                    await update_playlist(1, PlaylistUpdate(name="New", is_enabled=False), session=SESSION, db=db)
                assert exc_info.value.status_code == 502

            async with maker() as db:
                playlist = (await db.execute(select(Playlist))).scalar_one()
                assert playlist.name == "Old"
                assert playlist.is_enabled is True
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_spotify_404_renames_locally(self, spotify):
        spotify.update_playlist_details.side_effect = _status_error(404)
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Old", spotify_playlist_id="sp1"))
                await db.commit()

                response = await update_playlist(1, PlaylistUpdate(name="New"), session=SESSION, db=db)
                assert response.name == "New"
        finally:
            await engine.dispose()
