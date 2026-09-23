"""Tests for podcasts-router fixes (issue #182 batch).

- ``/podcasts/sync`` used to 500 when Spotify handed back the same show twice
  (the subscription list can shift under pagination mid-sync): with autoflush
  off the existence SELECT can't see the first pending insert, so the repeat
  hit the ``spotify_id`` unique constraint and sank the whole sync.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.routers import podcasts as podcasts_module
from app.database import Base
from app.models import Podcast, User
from app.rate_limit import limiter
from app.routers.podcasts import sync_podcasts
from app.services.encryption import get_encryption_service


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


def _user(spotify_id="spotify-user"):
    encryption = get_encryption_service()
    return User(
        spotify_id=spotify_id,
        access_token=encryption.encrypt("access-token"),
        refresh_token=encryption.encrypt("refresh-token"),
        token_expires_at=datetime.now(UTC),
    )


def _show(spotify_id, name):
    return {"show": {"id": spotify_id, "name": name, "images": [], "publisher": "pub", "total_episodes": 3}}


class TestSyncDuplicateShows:
    @pytest.mark.asyncio
    async def test_repeated_show_in_response_is_inserted_once(self, monkeypatch):
        engine, maker = await _make_db()
        spotify = MagicMock()
        spotify.get_user_shows = AsyncMock(
            return_value={"items": [_show("showA", "A"), _show("showA", "A"), _show("showB", "B")]}
        )
        monkeypatch.setattr(podcasts_module, "SpotifyService", MagicMock(return_value=spotify))

        try:
            async with maker() as db:
                db.add(_user())
                await db.commit()

                result = await sync_podcasts(
                    request=MagicMock(),
                    session=SimpleNamespace(user_id=1),
                    db=db,
                )
                assert result["synced"] == 2
                assert result["new"] == 2

                count = (await db.execute(select(func.count()).select_from(Podcast))).scalar()
                assert count == 2
        finally:
            await engine.dispose()
