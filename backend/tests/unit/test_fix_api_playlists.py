"""Tests for playlist-router fixes (issue #182 batch).

- ``/playlists/run-all`` must not return raw exception strings per playlist,
  and must report partial results distinctly instead of lumping them in with
  failures (mirrors the single-run genericization from issue #161).
- Duplicate ``podcast_ids`` in one add request used to 500: with autoflush
  off, the existence SELECT can't see the first pending insert, so the second
  add hit the unique constraint.
- Schema bounds on name / spotify_playlist_id / podcast_ids.
"""

import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.routers import playlists as playlists_module
from app.database import Base
from app.jobs import locks
from app.models import Playlist, PlaylistPodcast, Podcast, User
from app.rate_limit import limiter
from app.routers.playlists import add_podcasts_to_playlist, run_all_playlist_updates
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistPodcastAdd,
    PlaylistPodcastReorder,
    PlaylistUpdate,
)
from app.services.playlist_builder import PlaylistUpdateResult


@pytest.fixture(autouse=True)
def _fresh_lock():
    """Fresh write lock per test — asyncio primitives bind to the running loop."""
    original = locks.playlist_write_lock
    locks.playlist_write_lock = asyncio.Lock()
    try:
        yield
    finally:
        locks.playlist_write_lock = original


@pytest.fixture(autouse=True)
def _limiter_disabled():
    """Direct route calls still pass through the slowapi wrapper; disable it
    so a MagicMock request doesn't have to satisfy the limiter."""
    limiter.enabled = False
    yield
    limiter.enabled = True


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


class TestAddPodcastsDedupe:
    @pytest.mark.asyncio
    async def test_duplicate_podcast_ids_in_one_request_add_once(self):
        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Playlist"))
                db.add(Podcast(spotify_id="show1", name="Show", total_episodes=0, unplayed_episodes=0))
                await db.commit()

                result = await add_podcasts_to_playlist(
                    playlist_id=1,
                    data=PlaylistPodcastAdd(podcast_ids=[1, 1, 1]),
                    session=SimpleNamespace(user_id=1),
                    db=db,
                )
                assert result["added"] == 1

                count = (await db.execute(select(func.count()).select_from(PlaylistPodcast))).scalar()
                assert count == 1
        finally:
            await engine.dispose()


class TestRunAllErrorReporting:
    @pytest.mark.asyncio
    async def test_raw_errors_genericized_and_partial_reported_distinctly(self, monkeypatch, caplog):
        engine, maker = await _make_db()
        raw_error = "OperationalError: database /var/secret/path.db is locked"
        results = [
            PlaylistUpdateResult(playlist_id=1, playlist_name="A", success=True, episode_count=5),
            PlaylistUpdateResult(playlist_id=2, playlist_name="B", success=False, episode_count=0, error=raw_error),
            PlaylistUpdateResult(
                playlist_id=3,
                playlist_name="C",
                success=False,
                episode_count=3,
                error="Episodes could not be fetched for: Show X",
                partial=True,
            ),
            PlaylistUpdateResult(playlist_id=4, playlist_name="D", success=True, episode_count=0, skipped=True),
        ]
        builder = MagicMock()
        builder.update_all_playlists = AsyncMock(return_value=results)
        monkeypatch.setattr(playlists_module, "PlaylistBuilder", MagicMock(return_value=builder))
        monkeypatch.setattr(playlists_module, "TokenManager", MagicMock())

        try:
            async with maker() as db:
                db.add(_user())
                await db.commit()
                with caplog.at_level(logging.ERROR, logger="app.routers.playlists"):
                    response = await run_all_playlist_updates(
                        request=MagicMock(),
                        session=SimpleNamespace(user_id=1),
                        db=db,
                    )
        finally:
            await engine.dispose()

        assert response["message"] == "Updated 1 playlists, 1 failed, 1 updated with warnings, 1 skipped (disabled)"

        by_id = {r["playlist_id"]: r for r in response["results"]}
        # Genuine failure: generic client message, raw text only in the log.
        assert by_id[2]["error"] == "Failed to update playlist. Check the server logs for details."
        assert raw_error not in str(response)
        assert any(raw_error in record.getMessage() for record in caplog.records)
        # Partial: keeps its own message (ours, not an exception string).
        assert by_id[3]["partial"] is True
        assert by_id[3]["error"] == "Episodes could not be fetched for: Show X"
        # Success / skipped carry no error.
        assert by_id[1]["error"] is None
        assert by_id[4]["error"] is None
        assert by_id[4]["skipped"] is True


class TestPlaylistSchemaBounds:
    def test_empty_name_rejected_on_create(self):
        with pytest.raises(ValidationError):
            PlaylistCreate(name="")

    def test_overlong_name_rejected_on_create(self):
        with pytest.raises(ValidationError):
            PlaylistCreate(name="x" * 256)

    def test_empty_name_rejected_on_update(self):
        with pytest.raises(ValidationError):
            PlaylistUpdate(name="")

    def test_overlong_spotify_playlist_id_rejected(self):
        with pytest.raises(ValidationError):
            PlaylistCreate(name="ok", spotify_playlist_id="x" * 65)

    def test_real_spotify_playlist_id_accepted(self):
        # Spotify IDs are 22 chars of base62.
        PlaylistCreate(name="ok", spotify_playlist_id="37i9dQZF1DXcBWIGoYBM5M")

    def test_podcast_ids_capped_on_add_and_reorder(self):
        with pytest.raises(ValidationError):
            PlaylistPodcastAdd(podcast_ids=list(range(501)))
        with pytest.raises(ValidationError):
            PlaylistPodcastReorder(podcast_ids=list(range(501)))
        # At the cap is fine.
        PlaylistPodcastAdd(podcast_ids=list(range(500)))


class TestAssignmentOverrides:
    """``PATCH /playlists/{id}/podcasts/{podcast_id}`` sets and clears overrides (issue #249)."""

    @pytest.mark.asyncio
    async def test_rows_resolve_through_defaults_and_overrides(self):
        from app.routers.playlists import list_playlist_podcasts, update_playlist_podcast
        from app.schemas.playlist import AssignmentOverrideUpdate

        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Morning", default_episode_limit=1, default_pick_from="newest"))
                db.add(
                    Podcast(spotify_id="story", name="Story", is_sequential=True, total_episodes=0, unplayed_episodes=0)
                )
                await db.commit()
                await add_podcasts_to_playlist(
                    playlist_id=1, data=PlaylistPodcastAdd(podcast_ids=[1]), session=SimpleNamespace(user_id=1), db=db
                )

                # Fresh row: limit from the playlist, direction from the sequential hint.
                listed = await list_playlist_podcasts(playlist_id=1, user_id=1, db=db)
                row = listed.items[0]
                assert (row.rule.episode_limit, row.rule.pick_from.value) == (1, "oldest")
                assert (row.rule.episode_limit_source, row.rule.pick_from_source) == ("playlist", "sequential")
                assert (row.override.episode_limit, row.override.pick_from) == (None, None)

                # Override the limit only; direction still inherits.
                updated = await update_playlist_podcast(
                    playlist_id=1,
                    podcast_id=1,
                    data=AssignmentOverrideUpdate(episode_limit=0),
                    session=SimpleNamespace(user_id=1),
                    db=db,
                )
                assert updated.rule.episode_limit == 0
                assert updated.rule.episode_limit_source == "override"
                assert updated.rule.pick_from_source == "sequential"

                # Explicit null clears the override; an absent field is untouched.
                cleared = await update_playlist_podcast(
                    playlist_id=1,
                    podcast_id=1,
                    data=AssignmentOverrideUpdate.model_validate({"episode_limit": None}),
                    session=SimpleNamespace(user_id=1),
                    db=db,
                )
                assert cleared.rule.episode_limit == 1
                assert cleared.rule.episode_limit_source == "playlist"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_unassigned_podcast_is_404(self):
        from fastapi import HTTPException

        from app.routers.playlists import update_playlist_podcast
        from app.schemas.playlist import AssignmentOverrideUpdate

        engine, maker = await _make_db()
        try:
            async with maker() as db:
                db.add(_user())
                db.add(Playlist(user_id=1, name="Morning"))
                await db.commit()
                with pytest.raises(HTTPException) as exc:
                    await update_playlist_podcast(
                        playlist_id=1,
                        podcast_id=99,
                        data=AssignmentOverrideUpdate(pick_from="oldest"),
                        session=SimpleNamespace(user_id=1),
                        db=db,
                    )
                assert exc.value.status_code == 404
        finally:
            await engine.dispose()
