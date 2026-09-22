"""``POST /podcasts/sync`` after issue #155.

- No per-show episode fetch, and no invented unplayed count: new shows start
  with ``unplayed_episodes = None`` ("not counted") and existing counts are
  left for the playlist build to maintain.
- Shows that have left the Spotify library are marked, and deleted only once
  they have stayed missing for ``UNSUBSCRIBE_GRACE`` — deleting cascades to
  playlist assignments, and one paginated walk is not a reliable snapshot.
"""

from datetime import UTC, datetime, timedelta
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
from app.routers.podcasts import UNSUBSCRIBE_GRACE, sync_podcasts
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
async def test_missing_show_is_marked_not_deleted_on_the_first_sync(maker, monkeypatch):
    _spotify(monkeypatch, [{"items": [_show("kept")], "total": 1}])
    async with maker() as db:
        await _seed(db, Podcast(spotify_id="kept", name="kept"), Podcast(spotify_id="gone", name="gone"))

        result = await _sync(db)

        assert (result["missing"], result["removed"]) == (1, 0)
        assert await _spotify_ids(db) == {"kept", "gone"}
        gone = (await db.execute(select(Podcast).where(Podcast.spotify_id == "gone"))).scalar_one()
        assert gone.missing_since is not None


@pytest.mark.asyncio
async def test_show_missing_past_the_grace_period_is_deleted_with_its_assignments(maker, monkeypatch):
    _spotify(monkeypatch, [{"items": [_show("kept")], "total": 1}])
    async with maker() as db:
        gone = Podcast(
            spotify_id="gone",
            name="gone",
            missing_since=datetime.now(UTC) - UNSUBSCRIBE_GRACE - timedelta(minutes=1),
        )
        user = await _seed(db, Podcast(spotify_id="kept", name="kept"), gone)
        playlist = Playlist(user_id=user.id, name="p", spotify_playlist_id="sp")
        db.add(playlist)
        await db.flush()
        db.add(PlaylistPodcast(playlist_id=playlist.id, podcast_id=gone.id, position=0))
        await db.commit()

        result = await _sync(db)

        assert (result["missing"], result["removed"]) == (0, 1)
        assert await _spotify_ids(db) == {"kept"}
        assert (await db.execute(select(PlaylistPodcast))).scalars().all() == []


@pytest.mark.asyncio
async def test_show_inside_the_grace_period_survives(maker, monkeypatch):
    _spotify(monkeypatch, [{"items": [_show("kept")], "total": 1}])
    async with maker() as db:
        marked_at = datetime.now(UTC) - UNSUBSCRIBE_GRACE + timedelta(hours=1)
        await _seed(
            db,
            Podcast(spotify_id="kept", name="kept"),
            Podcast(spotify_id="gone", name="gone", missing_since=marked_at),
        )

        result = await _sync(db)

        assert (result["missing"], result["removed"]) == (1, 0)
        gone = (await db.execute(select(Podcast).where(Podcast.spotify_id == "gone"))).scalar_one()
        # The clock keeps running from the first sync that missed it.
        assert abs((gone.missing_since - marked_at).total_seconds()) < 1


@pytest.mark.asyncio
async def test_resubscribing_clears_the_mark(maker, monkeypatch):
    """A show that reappears — including one an earlier walk simply lost —
    must not carry its old mark towards deletion."""
    _spotify(monkeypatch, [{"items": [_show("back")], "total": 1}])
    async with maker() as db:
        await _seed(
            db,
            Podcast(
                spotify_id="back",
                name="back",
                missing_since=datetime.now(UTC) - UNSUBSCRIBE_GRACE - timedelta(days=1),
            ),
        )

        result = await _sync(db)

        assert (result["missing"], result["removed"]) == (0, 0)
        back = (await db.execute(select(Podcast).where(Podcast.spotify_id == "back"))).scalar_one()
        assert back.missing_since is None


@pytest.mark.asyncio
async def test_archived_show_still_in_the_library_is_untouched(maker, monkeypatch):
    """Archiving only hides a show in the app (issue #247); it stays followed
    on Spotify, so it is still in the walk and must never be marked."""
    _spotify(monkeypatch, [{"items": [_show("hidden")], "total": 1}])
    async with maker() as db:
        await _seed(db, Podcast(spotify_id="hidden", name="hidden", is_archived=True))

        result = await _sync(db)

        assert (result["missing"], result["removed"]) == (0, 0)
        hidden = (await db.execute(select(Podcast).where(Podcast.spotify_id == "hidden"))).scalar_one()
        assert hidden.missing_since is None
        assert hidden.is_archived is True


@pytest.mark.asyncio
async def test_walk_seeing_every_page_still_marks(maker, monkeypatch):
    first = {"items": [_show(f"s{i}") for i in range(50)], "total": 51}
    second = {"items": [_show("s50")], "total": 51}
    _spotify(monkeypatch, [first, second])
    async with maker() as db:
        await _seed(db, Podcast(spotify_id="s50", name="s50"), Podcast(spotify_id="gone", name="gone"))

        result = await _sync(db)

        assert result["missing"] == 1
        assert await _spotify_ids(db) == {f"s{i}" for i in range(51)} | {"gone"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pages",
    [
        # A show fell between pages: fewer distinct shows than Spotify's total.
        [{"items": [_show("kept")], "total": 2}],
        # The library shrank mid-walk, so a short page reports a total the
        # stale IDs already satisfy. Nothing here confirms "other" is gone.
        [{"items": [_show(f"s{i}") for i in range(50)], "total": 51}, {"items": [], "total": 50}],
        # Spotify answered with nothing at all.
        [{"items": [], "total": 0}],
        # No total to check against.
        [{"items": [_show("kept")]}],
    ],
    ids=["short-of-total", "library-shrank-mid-walk", "empty-library", "no-total"],
)
async def test_incomplete_walk_marks_nothing(maker, monkeypatch, pages):
    _spotify(monkeypatch, pages)
    async with maker() as db:
        await _seed(db, Podcast(spotify_id="kept", name="kept"), Podcast(spotify_id="other", name="other"))

        result = await _sync(db)

        assert (result["missing"], result["removed"]) == (0, 0)
        assert {"kept", "other"} <= await _spotify_ids(db)
        for podcast in (await db.execute(select(Podcast))).scalars():
            assert podcast.missing_since is None
