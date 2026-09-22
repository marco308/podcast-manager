"""``POST /podcasts/sync`` after issue #155.

- No per-show episode fetch, and no invented unplayed count: new shows start
  with ``unplayed_episodes = None`` ("not counted") and existing counts are
  left for the playlist build to maintain.
- Shows that have left the Spotify library are pruned, but only when the walk
  provably saw the whole library — pruning cascades to playlist assignments.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.routers.podcasts as podcasts_module
from app.database import Base
from app.models import Playlist, PlaylistPodcast, Podcast, User
from app.rate_limit import limiter
from app.routers.podcasts import sync_podcasts
from app.services.encryption import get_encryption_service


@pytest.fixture(autouse=True)
def _limiter_disabled():
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    await engine.dispose()


def _show(spotify_id):
    return {"show": {"id": spotify_id, "name": spotify_id, "images": [], "publisher": "pub", "total_episodes": 3}}


def _spotify(monkeypatch, pages):
    spotify = MagicMock()
    spotify.get_user_shows = AsyncMock(side_effect=pages)
    spotify.get_show_episodes = AsyncMock(side_effect=AssertionError("sync must not fetch episodes"))
    monkeypatch.setattr(podcasts_module, "SpotifyService", MagicMock(return_value=spotify))
    return spotify


async def _seed(db, *podcasts):
    encryption = get_encryption_service()
    user = User(
        spotify_id="u",
        access_token=encryption.encrypt("a"),
        refresh_token=encryption.encrypt("r"),
        token_expires_at=datetime.now(UTC),
    )
    db.add(user)
    db.add_all(podcasts)
    await db.commit()
    return user


async def _sync(db):
    return await sync_podcasts(request=MagicMock(), session=SimpleNamespace(user_id=1), db=db)


async def _spotify_ids(db):
    return set((await db.execute(select(Podcast.spotify_id))).scalars().all())


@pytest.mark.asyncio
async def test_new_show_is_not_counted_and_existing_count_is_kept(maker, monkeypatch):
    _spotify(monkeypatch, [{"items": [_show("kept"), _show("new")], "total": 2}])
    async with maker() as db:
        await _seed(db, Podcast(spotify_id="kept", name="kept", unplayed_episodes=7))
        await _sync(db)

        rows = {p.spotify_id: p for p in (await db.execute(select(Podcast))).scalars()}
        assert rows["new"].unplayed_episodes is None
        assert rows["kept"].unplayed_episodes == 7


@pytest.mark.asyncio
async def test_unsubscribed_show_is_pruned_with_its_assignments(maker, monkeypatch):
    _spotify(monkeypatch, [{"items": [_show("kept")], "total": 1}])
    async with maker() as db:
        gone = Podcast(spotify_id="gone", name="gone")
        user = await _seed(db, Podcast(spotify_id="kept", name="kept"), gone)
        playlist = Playlist(user_id=user.id, name="p", spotify_playlist_id="sp")
        db.add(playlist)
        await db.flush()
        db.add(PlaylistPodcast(playlist_id=playlist.id, podcast_id=gone.id, position=0))
        await db.commit()

        result = await _sync(db)

        assert result["removed"] == 1
        assert await _spotify_ids(db) == {"kept"}
        assert (await db.execute(select(PlaylistPodcast))).scalars().all() == []


@pytest.mark.asyncio
async def test_prune_walks_every_page_before_deciding(maker, monkeypatch):
    first = {"items": [_show(f"s{i}") for i in range(50)], "total": 51}
    second = {"items": [_show("s50")], "total": 51}
    _spotify(monkeypatch, [first, second])
    async with maker() as db:
        await _seed(db, Podcast(spotify_id="s50", name="s50"), Podcast(spotify_id="gone", name="gone"))
        result = await _sync(db)

        assert result["removed"] == 1
        assert "s50" in await _spotify_ids(db)
        assert "gone" not in await _spotify_ids(db)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pages",
    [
        # A show fell between pages: fewer distinct shows than Spotify's total.
        [{"items": [_show("kept")], "total": 2}],
        # Spotify answered with nothing at all.
        [{"items": [], "total": 0}],
        # No total to check against.
        [{"items": [_show("kept")]}],
    ],
    ids=["short-of-total", "empty-library", "no-total"],
)
async def test_incomplete_walk_does_not_prune(maker, monkeypatch, pages):
    _spotify(monkeypatch, pages)
    async with maker() as db:
        await _seed(db, Podcast(spotify_id="kept", name="kept"), Podcast(spotify_id="other", name="other"))
        result = await _sync(db)

        assert result["removed"] == 0
        assert await _spotify_ids(db) == {"kept", "other"}
