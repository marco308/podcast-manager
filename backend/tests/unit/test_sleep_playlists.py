"""Sleep playlists: played episodes only, the served-episode ledger (issue #331)."""

import random
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.jobs import scheduler
from app.models import Playlist, PlaylistPodcast, Podcast, SleepEpisode, User
from app.models.playlist import Arrangement, PickFrom, PlaylistKind
from app.routers.playlists import create_playlist, update_playlist, update_playlist_podcast
from app.schemas.playlist import AssignmentOverrideUpdate, PlaylistCreate, PlaylistUpdate
from app.services.assignment_rules import resolve_rule
from app.services.playlist_builder import AssignmentEntry, PlaylistBuilder

SESSION = SimpleNamespace(user_id=1)


def _ep(ep_id, *, played, date="2026-01-01"):
    return {
        "id": ep_id,
        "uri": f"spotify:episode:{ep_id}",
        "release_date": date,
        "resume_point": {"fully_played": played},
    }


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


class TestEpisodeFilter:
    def test_standard_keeps_unplayed_not_served_by_sleep(self):
        builder = PlaylistBuilder(AsyncMock(), MagicMock())
        wanted = builder._episode_filter(SimpleNamespace(kind="standard"), {"slept"})
        assert wanted(_ep("new", played=False))
        assert not wanted(_ep("done", played=True))
        # Falling asleep to it made Spotify call it partially played again.
        assert not wanted(_ep("slept", played=False))

    def test_sleep_keeps_played_and_ledger_episodes(self):
        builder = PlaylistBuilder(AsyncMock(), MagicMock())
        wanted = builder._episode_filter(SimpleNamespace(kind="sleep"), {"slept"})
        assert wanted(_ep("done", played=True))
        assert wanted(_ep("slept", played=False))
        assert not wanted(_ep("new", played=False))
        assert not wanted({**_ep("gone", played=True), "is_playable": False})


class TestSleepRule:
    def test_sequential_hint_ignored_on_sleep(self):
        podcast = SimpleNamespace(is_sequential=True)
        sleep = SimpleNamespace(kind="sleep", default_episode_limit=10, default_pick_from="random")
        standard = SimpleNamespace(kind="standard", default_episode_limit=10, default_pick_from="newest")
        assert resolve_rule(sleep, podcast, None).pick_from == PickFrom.RANDOM
        assert resolve_rule(standard, podcast, None).pick_from == PickFrom.OLDEST


class TestSleepBuild:
    @pytest.mark.asyncio
    async def test_random_sample_of_played_episodes(self):
        episodes = [_ep(f"p{i}", played=True, date=f"2025-01-{i + 1:02d}") for i in range(20)]
        episodes += [_ep("u1", played=False, date="2026-01-01")]
        spotify = MagicMock()
        spotify.get_show_episodes = AsyncMock(return_value={"items": episodes, "next": None, "total": 21})
        podcast = SimpleNamespace(spotify_id="show", name="Show", is_sequential=False)
        playlist = SimpleNamespace(
            id=1,
            name="Sleep",
            kind="sleep",
            default_episode_limit=10,
            default_pick_from="random",
            arrangement="shuffle",
            date_direction="oldest_first",
        )
        assignment = SimpleNamespace(episode_limit=None, pick_from=None, position=0)

        builder = PlaylistBuilder(AsyncMock(), MagicMock())
        builder._rng = random.Random(1)
        builder._get_spotify_client = AsyncMock(return_value=spotify)
        builder._load_sleep_ledger = AsyncMock(return_value=set())
        builder._get_playlist_podcasts = AsyncMock(return_value=[AssignmentEntry(podcast, assignment)])

        uris, failed = await builder._build_playlist_content(playlist)

        assert failed == []
        assert len(uris) == 10
        assert len(set(uris)) == 10
        assert "spotify:episode:u1" not in uris
        # The unplayed count is still Spotify's, not the sleep selection's.
        assert podcast.unplayed_episodes == 1

    @pytest.mark.asyncio
    async def test_served_episodes_are_recorded(self, db):
        builder = PlaylistBuilder(db, MagicMock())
        await builder._record_sleep_served(["spotify:episode:a", "spotify:episode:b"])
        await db.commit()
        await builder._record_sleep_served(["spotify:episode:b", "spotify:episode:c"])
        await db.commit()
        assert await builder._load_sleep_ledger() == {"a", "b", "c"}


class TestCleanupSkipsSleep:
    @pytest.mark.asyncio
    async def test_candidates_exclude_sleep(self, db):
        db.add_all(
            [
                Playlist(user_id=1, name="Std", kind="standard"),
                Playlist(user_id=1, name="Sleep", kind="sleep"),
                Playlist(user_id=1, name="Off", kind="standard", is_enabled=False),
            ]
        )
        await db.commit()
        result = await db.execute(select(Playlist.name).where(scheduler._cleanup_candidates()))
        assert result.scalars().all() == ["Std"]


class TestSleepApi:
    @pytest.mark.asyncio
    async def test_create_sleep_gets_defaults(self, db):
        result = await create_playlist(PlaylistCreate(name="Sleep", kind="sleep"), session=SESSION, db=db)
        assert result.kind == PlaylistKind.SLEEP
        assert result.arrangement == Arrangement.SHUFFLE
        assert result.default_pick_from == PickFrom.RANDOM
        assert result.default_episode_limit == 10

    @pytest.mark.asyncio
    async def test_create_sleep_keeps_explicit_settings(self, db):
        result = await create_playlist(
            PlaylistCreate(name="Sleep", kind="sleep", default_episode_limit=3, default_pick_from="oldest"),
            session=SESSION,
            db=db,
        )
        assert result.default_episode_limit == 3
        assert result.default_pick_from == PickFrom.OLDEST
        assert result.arrangement == Arrangement.SHUFFLE

    @pytest.mark.asyncio
    async def test_random_refused_on_standard(self, db):
        with pytest.raises(HTTPException) as exc:
            await create_playlist(PlaylistCreate(name="P", default_pick_from="random"), session=SESSION, db=db)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_switch_kinds(self, db):
        created = await create_playlist(PlaylistCreate(name="P"), session=SESSION, db=db)
        podcast = Podcast(spotify_id="show", name="Show")
        db.add(podcast)
        await db.flush()
        db.add(PlaylistPodcast(playlist_id=created.id, podcast_id=podcast.id, position=0))
        await db.commit()

        sleep = await update_playlist(created.id, PlaylistUpdate(kind="sleep"), session=SESSION, db=db)
        assert sleep.default_pick_from == PickFrom.RANDOM
        await update_playlist_podcast(
            created.id, podcast.id, AssignmentOverrideUpdate(pick_from="random"), session=SESSION, db=db
        )

        back = await update_playlist(created.id, PlaylistUpdate(kind="standard"), session=SESSION, db=db)
        assert back.kind == PlaylistKind.STANDARD
        assert back.default_pick_from == PickFrom.NEWEST
        row = (await db.execute(select(PlaylistPodcast))).scalar_one()
        await db.refresh(row)
        assert row.pick_from is None

        with pytest.raises(HTTPException) as exc:
            await update_playlist_podcast(
                created.id, podcast.id, AssignmentOverrideUpdate(pick_from="random"), session=SESSION, db=db
            )
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_ledger_model_registered(self, db):
        db.add(SleepEpisode(episode_id="x", first_served_at=datetime.now(UTC), last_served_at=datetime.now(UTC)))
        await db.commit()
