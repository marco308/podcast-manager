"""Each playlist's last build result (issue #246).

``PlaylistBuilder.update_playlist`` — the one path used by the daily rebuild
and by manual runs — stores the outcome on the playlist, so a failed or
partial build shows next to "Updated 3 hours ago" instead of only in a toast.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Playlist, User
from app.routers.playlists import _build_playlist_response
from app.services.encryption import TokenDecryptionError
from app.services.playlist_builder import (
    EpisodeFetchError,
    PlaylistBuilder,
    PlaylistBuildError,
    describe_build_failure,
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        user = User(
            spotify_id="me",
            access_token="encrypted",
            refresh_token="encrypted",
            token_expires_at=datetime.now(UTC),
        )
        session.add(user)
        session.add(Playlist(user_id=1, name="Commute", spotify_playlist_id="sp1"))
        await session.commit()
        yield session
    await engine.dispose()


async def _builder(db, *, content=None, build_error=None, write_error=None):
    user = (await db.execute(select(User))).scalar_one()
    builder = PlaylistBuilder(db, user, token_manager=MagicMock())
    builder._ensure_spotify_playlist = AsyncMock(return_value="sp1")
    builder._build_playlist_content = AsyncMock(return_value=content, side_effect=build_error)
    spotify = AsyncMock()
    spotify.replace_playlist_items = AsyncMock(side_effect=write_error)
    builder._get_spotify_client = AsyncMock(return_value=spotify)
    return builder


async def _playlist(db) -> Playlist:
    return (await db.execute(select(Playlist))).scalar_one()


def _http_error(status: int, method: str = "PUT") -> httpx.HTTPStatusError:
    request = httpx.Request(method, "https://api.spotify.com/v1/playlists/sp1/items")
    return httpx.HTTPStatusError("err", request=request, response=httpx.Response(status, request=request))


class TestLastRunRecorded:
    @pytest.mark.asyncio
    async def test_success(self, db):
        builder = await _builder(db, content=(["spotify:episode:a"], []))
        playlist = await _playlist(db)

        await builder.update_playlist(playlist)

        db.expire_all()
        playlist = await _playlist(db)
        assert playlist.last_run_status == "success"
        assert playlist.last_run_error is None
        assert playlist.last_run_at is not None
        assert playlist.last_run_at == playlist.last_updated_at

    @pytest.mark.asyncio
    async def test_partial_names_the_podcasts(self, db):
        builder = await _builder(db, content=(["spotify:episode:a"], ["Show B"]))

        await builder.update_playlist(await _playlist(db))

        db.expire_all()
        playlist = await _playlist(db)
        assert playlist.last_run_status == "partial"
        assert playlist.last_run_error == "Episodes could not be fetched for: Show B"

    @pytest.mark.asyncio
    async def test_failure_keeps_last_updated_and_hides_exception_text(self, db):
        builder = await _builder(db, content=(["spotify:episode:a"], []), write_error=_http_error(502))
        playlist = await _playlist(db)

        result = await builder.update_playlist(playlist)

        assert result.success is False
        db.expire_all()
        playlist = await _playlist(db)
        assert playlist.last_run_status == "failed"
        assert playlist.last_run_error == "Spotify returned an error (502), so the playlist was left unchanged."
        assert playlist.last_run_at is not None
        # Nothing was written to Spotify, so "Updated …" doesn't move.
        assert playlist.last_updated_at is None

    @pytest.mark.asyncio
    async def test_a_later_success_clears_the_error(self, db):
        failing = await _builder(db, build_error=PlaylistBuildError("all failed"))
        await failing.update_playlist(await _playlist(db))
        working = await _builder(db, content=([], []))
        await working.update_playlist(await _playlist(db))

        db.expire_all()
        playlist = await _playlist(db)
        assert (playlist.last_run_status, playlist.last_run_error) == ("success", None)

    @pytest.mark.asyncio
    async def test_disabled_playlist_keeps_its_previous_result(self, db):
        playlist = await _playlist(db)
        playlist.is_enabled = False
        playlist.last_run_status = "partial"
        await db.commit()
        builder = await _builder(db, content=([], []))

        result = await builder.update_playlist(playlist)

        assert result.skipped
        db.expire_all()
        assert (await _playlist(db)).last_run_status == "partial"

    @pytest.mark.asyncio
    async def test_returned_by_the_api(self, db):
        builder = await _builder(db, content=([], ["Show B"]))
        await builder.update_playlist(await _playlist(db))

        response = _build_playlist_response(await _playlist(db), 0).model_dump(mode="json")

        assert response["last_run_status"] == "partial"
        assert response["last_run_error"] == "Episodes could not be fetched for: Show B"
        assert response["last_run_at"] is not None


class TestDescribeBuildFailure:
    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (_http_error(429, "GET"), "rate limit"),
            (_http_error(401, "GET"), "refused the sign-in"),
            (TokenDecryptionError("key"), "Sign in again"),
            (PlaylistBuildError("x"), "No podcast's episodes"),
            (RuntimeError("secret detail"), "Check the server logs"),
        ],
    )
    def test_messages(self, exc, expected):
        message = describe_build_failure(exc)
        assert expected in message
        assert "secret" not in message

    def test_follows_the_cause_chain(self):
        try:
            try:
                raise _http_error(429, "GET")
            except httpx.HTTPStatusError as inner:
                raise EpisodeFetchError("wrapped") from inner
        except EpisodeFetchError as outer:
            assert "rate limit" in describe_build_failure(outer)
