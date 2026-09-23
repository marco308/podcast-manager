"""Linking an existing Spotify playlist requires owning it (issue #245).

Every rebuild fully replaces the linked playlist's contents, so the server
must refuse IDs the user doesn't own (or that don't exist), and the picker
endpoint only offers playlists the user owns.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.routers import playlists as playlists_module
from app.database import Base
from app.models import Playlist, User
from app.routers.playlists import create_playlist, list_spotify_playlists, update_playlist
from app.schemas.playlist import PlaylistCreate, PlaylistUpdate

OWN_ID = "3cEYpjA9oz9GiPac4AsH4n"
OTHER_ID = "37i9dQZF1DXcBWIGoYBM5M"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        session.add(
            User(
                spotify_id="me",
                access_token="encrypted",
                refresh_token="encrypted",
                token_expires_at=datetime.now(UTC),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.spotify.com/v1/playlists/x")
    return httpx.HTTPStatusError("err", request=request, response=httpx.Response(status, request=request))


@pytest.fixture
def spotify(monkeypatch):
    client = MagicMock()
    client.get_playlist = AsyncMock(return_value={"id": OWN_ID, "name": "Mine", "owner": {"id": "me"}})
    client.get_user_playlists = AsyncMock()
    monkeypatch.setattr(
        playlists_module,
        "spotify_client",
        AsyncMock(return_value=(client, SimpleNamespace(force_refresh=AsyncMock()))),
    )
    return client


SESSION = SimpleNamespace(user_id=1)


class TestSchema:
    def test_blank_id_means_no_link(self):
        assert PlaylistCreate(name="x", spotify_playlist_id="  ").spotify_playlist_id is None
        assert PlaylistUpdate(spotify_playlist_id="").spotify_playlist_id is None

    def test_non_base62_rejected(self):
        with pytest.raises(ValidationError):
            PlaylistCreate(name="x", spotify_playlist_id="../me/shows")


class TestLinkOwnership:
    @pytest.mark.asyncio
    async def test_owned_playlist_links(self, db, spotify):
        result = await create_playlist(PlaylistCreate(name="P", spotify_playlist_id=OWN_ID), session=SESSION, db=db)
        assert result.spotify_playlist_id == OWN_ID
        spotify.get_playlist.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_someone_elses_playlist_rejected(self, db, spotify):
        spotify.get_playlist.return_value = {"id": OTHER_ID, "owner": {"id": "spotify"}}
        with pytest.raises(HTTPException) as exc:
            await create_playlist(PlaylistCreate(name="P", spotify_playlist_id=OTHER_ID), session=SESSION, db=db)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_id_rejected(self, db, spotify):
        spotify.get_playlist.side_effect = _status_error(404)
        with pytest.raises(HTTPException) as exc:
            await create_playlist(PlaylistCreate(name="P", spotify_playlist_id=OTHER_ID), session=SESSION, db=db)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_spotify_outage_is_502_not_a_link(self, db, spotify):
        spotify.get_playlist.side_effect = _status_error(503)
        with pytest.raises(HTTPException) as exc:
            await create_playlist(PlaylistCreate(name="P", spotify_playlist_id=OWN_ID), session=SESSION, db=db)
        assert exc.value.status_code == 502

    @pytest.mark.asyncio
    async def test_no_id_skips_spotify(self, db, spotify):
        await create_playlist(PlaylistCreate(name="P"), session=SESSION, db=db)
        spotify.get_playlist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_rejects_unowned_and_keeps_old_link(self, db, spotify):
        db.add(Playlist(user_id=1, name="P", spotify_playlist_id=OWN_ID))
        await db.commit()
        spotify.get_playlist.return_value = {"id": OTHER_ID, "owner": {"id": "someone"}}
        with pytest.raises(HTTPException):
            await update_playlist(1, PlaylistUpdate(spotify_playlist_id=OTHER_ID), session=SESSION, db=db)
        await db.rollback()
        playlist = await db.get(Playlist, 1)
        assert playlist.spotify_playlist_id == OWN_ID

    @pytest.mark.asyncio
    async def test_update_with_unchanged_id_skips_spotify(self, db, spotify):
        db.add(Playlist(user_id=1, name="P", spotify_playlist_id=OWN_ID))
        await db.commit()
        # Not a rename: that path calls Spotify for its own reasons (issue #247).
        await update_playlist(1, PlaylistUpdate(is_enabled=False, spotify_playlist_id=OWN_ID), session=SESSION, db=db)
        spotify.get_playlist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_linked_elsewhere_rejected(self, db, spotify):
        db.add(Playlist(user_id=1, name="First", spotify_playlist_id=OWN_ID))
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await create_playlist(PlaylistCreate(name="Second", spotify_playlist_id=OWN_ID), session=SESSION, db=db)
        assert exc.value.status_code == 409


class TestListSpotifyPlaylists:
    @pytest.mark.asyncio
    async def test_only_owned_listed_across_pages(self, db, spotify):
        db.add(Playlist(user_id=1, name="Linked", spotify_playlist_id=OWN_ID))
        await db.commit()
        spotify.get_user_playlists.side_effect = [
            {
                "items": [
                    {
                        "id": OWN_ID,
                        "name": "Mine",
                        "owner": {"id": "me"},
                        "images": [{"url": "u"}],
                        "items": {"total": 7},
                    },
                    {"id": OTHER_ID, "name": "Followed", "owner": {"id": "spotify"}},
                    None,
                ],
                "next": "page2",
            },
            {"items": [{"id": "abc", "name": "Music", "owner": {"id": "me"}, "tracks": {"total": 3}}], "next": None},
        ]

        result = await list_spotify_playlists(user_id=1, db=db)

        assert [(o.id, o.item_count, o.linked_playlist_id) for o in result.items] == [
            (OWN_ID, 7, 1),
            ("abc", 3, None),
        ]
        assert result.items[0].image_url == "u"
        assert spotify.get_user_playlists.await_args_list[1].kwargs["offset"] == 50


class TestUnlink:
    @pytest.mark.asyncio
    async def test_explicit_null_clears_the_link(self, db, spotify):
        db.add(Playlist(user_id=1, name="P", spotify_playlist_id=OWN_ID))
        await db.commit()
        result = await update_playlist(1, PlaylistUpdate(spotify_playlist_id=None), session=SESSION, db=db)
        assert result.spotify_playlist_id is None
        spotify.get_playlist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_absent_field_leaves_the_link_alone(self, db, spotify):
        db.add(Playlist(user_id=1, name="P", spotify_playlist_id=OWN_ID))
        await db.commit()
        result = await update_playlist(1, PlaylistUpdate(is_enabled=False), session=SESSION, db=db)
        assert result.spotify_playlist_id == OWN_ID


class TestDuplicateLinkRace:
    @pytest.mark.asyncio
    async def test_constraint_turns_a_lost_race_into_409(self, db, spotify, monkeypatch):
        """Both savers pass the pre-check; the unique constraint stops the second."""
        db.add(Playlist(user_id=1, name="First", spotify_playlist_id=OWN_ID))
        await db.commit()
        # Simulate the concurrent saver: the clash SELECT sees nothing.
        monkeypatch.setattr(playlists_module, "_check_spotify_playlist_link", AsyncMock())

        with pytest.raises(HTTPException) as exc:
            await create_playlist(PlaylistCreate(name="Second", spotify_playlist_id=OWN_ID), session=SESSION, db=db)

        assert exc.value.status_code == 409
