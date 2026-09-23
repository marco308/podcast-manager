"""Input validation and write races in the playlist/podcast routers.

- Reorder must name every assigned podcast exactly once; a partial or
  repeated list used to leave two rows on one position.
- Add loads podcasts and assignments in two queries, and a concurrent add of
  the same pair is a 409 rather than an IntegrityError 500.
- ``/podcasts/{ref}`` treats only ASCII digits as an id ("²".isdigit() is
  True, but int("²") raises).
- IDs too big for SQLite's INTEGER are a 422/404, not an OverflowError 500.
- Unfollowing a podcast holds ``library_sync_lock``; deleting a playlist
  holds ``playlist_write_lock`` even without ``remove_from_spotify``.
- The Spotify playlist picker says when it stopped at its page cap.
- A PATCH that links and renames refuses a lost link race before renaming.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.jobs import locks
from app.models import Playlist, PlaylistPodcast, Podcast, User
from app.routers import playlists as playlists_module
from app.routers import podcasts as podcasts_module
from app.routers.auth import get_current_user_id, validate_csrf_token
from app.routers.playlists import (
    add_podcasts_to_playlist,
    delete_playlist,
    list_spotify_playlists,
    reorder_playlist_podcasts,
    update_playlist,
)
from app.routers.podcasts import get_podcast, unfollow_podcast
from app.schemas.playlist import DB_ID_MAX, PlaylistPodcastAdd, PlaylistPodcastReorder, PlaylistUpdate

SESSION = SimpleNamespace(user_id=1)
OWN_ID = "3cEYpjA9oz9GiPac4AsH4n"


@pytest.fixture(autouse=True)
def _fresh_locks():
    """Fresh locks per test — asyncio primitives bind to the running loop."""
    originals = locks.playlist_write_lock, locks.library_sync_lock
    locks.playlist_write_lock = asyncio.Lock()
    locks.library_sync_lock = asyncio.Lock()
    try:
        yield
    finally:
        locks.playlist_write_lock, locks.library_sync_lock = originals


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db(maker):
    """A user, one playlist and three podcasts (ids 1..3)."""
    async with maker() as session:
        session.add(
            User(
                spotify_id="me",
                access_token="encrypted",
                refresh_token="encrypted",
                token_expires_at=datetime.now(UTC),
            )
        )
        session.add(Playlist(user_id=1, name="Playlist"))
        for n in (1, 2, 3):
            session.add(Podcast(spotify_id=f"show{n}", name=f"Show {n}", total_episodes=0))
        await session.commit()
        yield session


async def _assign(db, *podcast_ids):
    await add_podcasts_to_playlist(1, PlaylistPodcastAdd(podcast_ids=list(podcast_ids)), session=SESSION, db=db)


async def _positions(db) -> dict[int, int]:
    rows = await db.execute(select(PlaylistPodcast.podcast_id, PlaylistPodcast.position))
    return dict(rows.all())


class TestReorder:
    @pytest.mark.asyncio
    async def test_full_list_sets_positions(self, db):
        await _assign(db, 1, 2, 3)
        await reorder_playlist_podcasts(1, PlaylistPodcastReorder(podcast_ids=[3, 1, 2]), session=SESSION, db=db)
        assert await _positions(db) == {3: 1, 1: 2, 2: 3}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "order",
        [
            pytest.param([3], id="partial"),
            pytest.param([3, 3, 1], id="duplicate"),
            pytest.param([1, 2, 3, 3], id="duplicate-of-full"),
            pytest.param([1, 2, 99], id="unassigned"),
        ],
    )
    async def test_bad_list_is_400_and_changes_nothing(self, db, order):
        await _assign(db, 1, 2, 3)
        with pytest.raises(HTTPException) as exc:
            await reorder_playlist_podcasts(1, PlaylistPodcastReorder(podcast_ids=order), session=SESSION, db=db)
        assert exc.value.status_code == 400
        await db.rollback()
        assert await _positions(db) == {1: 1, 2: 2, 3: 3}

    @pytest.mark.asyncio
    async def test_one_query_for_the_assignments(self, db, monkeypatch):
        await _assign(db, 1, 2, 3)
        execute = AsyncMock(wraps=db.execute)
        monkeypatch.setattr(db, "execute", execute)
        await reorder_playlist_podcasts(1, PlaylistPodcastReorder(podcast_ids=[2, 3, 1]), session=SESSION, db=db)
        # Playlist lookup + one assignment load, however long the list.
        assert execute.await_count == 2


class TestAddPodcasts:
    @pytest.mark.asyncio
    async def test_query_count_does_not_grow_with_ids(self, db, monkeypatch):
        execute = AsyncMock(wraps=db.execute)
        monkeypatch.setattr(db, "execute", execute)
        result = await add_podcasts_to_playlist(
            1, PlaylistPodcastAdd(podcast_ids=[1, 2, 3, 99]), session=SESSION, db=db
        )
        assert result["added"] == 3
        # Playlist lookup, max position, known podcasts, existing assignments.
        assert execute.await_count == 4

    @pytest.mark.asyncio
    async def test_skips_archived_and_already_assigned(self, db):
        await _assign(db, 1)
        archived = await db.get(Podcast, 2)
        archived.is_archived = True
        await db.commit()

        result = await add_podcasts_to_playlist(1, PlaylistPodcastAdd(podcast_ids=[2, 1, 3]), session=SESSION, db=db)

        assert result["added"] == 1
        assert await _positions(db) == {1: 1, 3: 2}

    @pytest.mark.asyncio
    async def test_concurrent_add_of_the_same_pair_is_409(self, db, maker, monkeypatch):
        """Both adds pass the "already assigned" check; the constraint stops the second."""
        real_commit = db.commit

        async def commit_after_the_other_request():
            # The other request commits its row between our check and our insert.
            monkeypatch.setattr(db, "commit", real_commit)
            async with maker() as other:
                other.add(PlaylistPodcast(playlist_id=1, podcast_id=1, position=1))
                await other.commit()
            await real_commit()

        monkeypatch.setattr(db, "commit", commit_after_the_other_request)

        with pytest.raises(HTTPException) as exc:
            await _assign(db, 1)
        assert exc.value.status_code == 409

        count = (await db.execute(select(func.count()).select_from(PlaylistPodcast))).scalar()
        assert count == 1


class TestPodcastRef:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "ref",
        [
            pytest.param("²", id="superscript-two"),
            pytest.param("١", id="arabic-indic-one"),
            pytest.param(str(DB_ID_MAX + 1), id="past-int64"),
            pytest.param("9" * 5000, id="past-int-digit-limit"),
            pytest.param("0" * 5000, id="zeros"),
        ],
    )
    async def test_odd_refs_are_404_not_500(self, db, ref):
        with pytest.raises(HTTPException) as exc:
            await get_podcast(podcast_id=ref, user_id=1, db=db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_leading_zeros_still_resolve(self, db):
        response = await get_podcast(podcast_id="002", user_id=1, db=db)
        assert response.id == 2


class TestOversizedIds:
    """Bounds on path, query and body IDs are enforced before the database."""

    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.include_router(playlists_module.router)
        app.include_router(podcasts_module.router)

        async def no_db():
            yield MagicMock()

        app.dependency_overrides[get_db] = no_db
        app.dependency_overrides[get_current_user_id] = lambda: 1
        app.dependency_overrides[validate_csrf_token] = lambda: SESSION
        return TestClient(app)

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", f"/playlists/{2**63}"),
            ("GET", "/playlists/0"),
            ("DELETE", f"/playlists/{2**63}"),
            ("GET", f"/playlists/{2**63}/podcasts"),
            ("PATCH", f"/playlists/1/podcasts/{2**63}"),
            ("DELETE", f"/playlists/1/podcasts/{2**63}"),
            ("POST", f"/playlists/{2**63}/run"),
            ("GET", f"/podcasts?offset={2**63}"),
        ],
    )
    def test_path_and_query_ids_are_422(self, client, method, path):
        response = client.request(method, path, json={})
        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("method", "path"),
        [("POST", "/playlists/1/podcasts"), ("PUT", "/playlists/1/podcasts/reorder")],
    )
    @pytest.mark.parametrize("bad_id", [2**63, 0, -1])
    def test_body_ids_are_422(self, client, method, path, bad_id):
        response = client.request(method, path, json={"podcast_ids": [1, bad_id]})
        assert response.status_code == 422


class TestUnfollowTakesTheSyncLock:
    @pytest.fixture
    def spotify(self, monkeypatch):
        client = MagicMock()
        client.unfollow_show = AsyncMock()
        monkeypatch.setattr(
            podcasts_module,
            "spotify_client",
            AsyncMock(return_value=(client, SimpleNamespace(force_refresh=AsyncMock()))),
        )
        return client

    @pytest.mark.asyncio
    async def test_busy_sync_is_409_and_nothing_changes(self, db, spotify, monkeypatch):
        monkeypatch.setattr(podcasts_module, "SYNC_LOCK_WAIT_SECONDS", 0.05)
        await locks.library_sync_lock.acquire()
        try:
            with pytest.raises(HTTPException) as exc:
                await unfollow_podcast("1", session=SESSION, db=db)
        finally:
            locks.library_sync_lock.release()

        assert exc.value.status_code == 409
        spotify.unfollow_show.assert_not_awaited()
        assert await db.get(Podcast, 1) is not None

    @pytest.mark.asyncio
    async def test_unfollow_deletes_the_podcast_and_its_assignments(self, db, spotify):
        await _assign(db, 1, 2)

        await unfollow_podcast("1", session=SESSION, db=db)

        spotify.unfollow_show.assert_awaited_once()
        assert spotify.unfollow_show.await_args.args == ("show1",)
        assert not locks.library_sync_lock.locked()
        assert (await db.execute(select(Podcast.id))).scalars().all() == [2, 3]
        assert await _positions(db) == {2: 2}


class TestDeleteTakesTheWriteLock:
    @pytest.mark.asyncio
    async def test_busy_rebuild_is_409_and_the_row_stays(self, db, monkeypatch):
        monkeypatch.setattr(playlists_module, "WRITE_LOCK_WAIT_SECONDS", 0.05)
        await locks.playlist_write_lock.acquire()
        try:
            with pytest.raises(HTTPException) as exc:
                await delete_playlist(1, remove_from_spotify=False, session=SESSION, db=db)
        finally:
            locks.playlist_write_lock.release()

        assert exc.value.status_code == 409
        assert await db.get(Playlist, 1) is not None

    @pytest.mark.asyncio
    async def test_free_lock_deletes(self, db):
        await delete_playlist(1, remove_from_spotify=False, session=SESSION, db=db)
        assert not locks.playlist_write_lock.locked()
        assert (await db.execute(select(func.count()).select_from(Playlist))).scalar() == 0


class TestSpotifyPlaylistTruncation:
    @pytest.fixture
    def spotify(self, monkeypatch):
        client = MagicMock()
        client.get_user_playlists = AsyncMock()
        monkeypatch.setattr(
            playlists_module,
            "spotify_client",
            AsyncMock(return_value=(client, SimpleNamespace(force_refresh=AsyncMock()))),
        )
        return client

    @pytest.mark.asyncio
    async def test_cap_reached_with_more_left_is_truncated(self, db, spotify):
        spotify.get_user_playlists.return_value = {"items": [], "next": "more"}
        result = await list_spotify_playlists(user_id=1, db=db)
        assert result.truncated is True
        assert spotify.get_user_playlists.await_count == playlists_module.SPOTIFY_PLAYLIST_MAX_PAGES

    @pytest.mark.asyncio
    async def test_last_page_on_the_cap_is_not_truncated(self, db, spotify):
        pages = [{"items": [], "next": "more"}] * (playlists_module.SPOTIFY_PLAYLIST_MAX_PAGES - 1)
        spotify.get_user_playlists.side_effect = [*pages, {"items": [], "next": None}]
        result = await list_spotify_playlists(user_id=1, db=db)
        assert result.truncated is False


class TestLinkAndRename:
    @pytest.fixture
    def spotify(self, monkeypatch):
        client = MagicMock()
        client.update_playlist_details = AsyncMock()
        token_manager = MagicMock(get_token=AsyncMock(return_value="token"), force_refresh=AsyncMock())
        monkeypatch.setattr(
            playlists_module,
            "spotify_client",
            AsyncMock(return_value=(client, token_manager)),
        )
        return client

    @pytest.mark.asyncio
    async def test_lost_link_race_is_409_before_the_rename(self, db, spotify, monkeypatch):
        db.add(Playlist(user_id=1, name="Other", spotify_playlist_id=OWN_ID))
        await db.commit()
        # The concurrent saver: the pre-check sees no clash.
        monkeypatch.setattr(playlists_module, "_check_spotify_playlist_link", AsyncMock())

        with pytest.raises(HTTPException) as exc:
            await update_playlist(1, PlaylistUpdate(name="New", spotify_playlist_id=OWN_ID), session=SESSION, db=db)

        assert exc.value.status_code == 409
        spotify.update_playlist_details.assert_not_awaited()
        playlist = await db.get(Playlist, 1)
        assert (playlist.name, playlist.spotify_playlist_id) == ("Playlist", None)

    @pytest.mark.asyncio
    async def test_link_and_rename_together_still_work(self, db, spotify, monkeypatch):
        monkeypatch.setattr(playlists_module, "_check_spotify_playlist_link", AsyncMock())

        result = await update_playlist(
            1, PlaylistUpdate(name="New", spotify_playlist_id=OWN_ID), session=SESSION, db=db
        )

        assert (result.name, result.spotify_playlist_id) == ("New", OWN_ID)
        spotify.update_playlist_details.assert_awaited_once()
        assert spotify.update_playlist_details.await_args.args[0] == OWN_ID
