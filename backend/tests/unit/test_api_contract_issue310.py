"""API contract tests (issue #310).

- ``PATCH /playlists/{id}`` refuses an explicit ``null`` on a field a playlist
  can't be without, instead of answering 200 for a no-op. A ``null``
  ``spotify_playlist_id`` still unlinks.
- The endpoints that used to return an untyped ``dict`` have response models,
  and their JSON is the same as before: same keys, conditional keys only when
  they used to be sent.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.jobs import locks
from app.main import app as main_app
from app.models import Playlist, PlaylistPodcast, Podcast, User
from app.rate_limit import limiter
from app.routers import auth as auth_module
from app.routers import jobs as jobs_module
from app.routers import playlists as playlists_module
from app.routers import podcasts as podcasts_module
from app.routers.auth import get_current_session, get_current_user_id, validate_csrf_token
from app.schemas.playlist import PlaylistUpdate
from app.services.library_sync import LibrarySyncResult
from app.services.playlist_builder import PlaylistUpdateResult

SESSION = SimpleNamespace(user_id=1, csrf_token="csrf")
LINKED_ID = "3cEYpjA9oz9GiPac4AsH4n"

NON_NULLABLE = [
    "name",
    "is_enabled",
    "kind",
    "default_episode_limit",
    "default_pick_from",
    "arrangement",
    "date_direction",
]


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


@pytest.fixture(autouse=True)
def _limiter_disabled():
    limiter.enabled = False
    yield
    limiter.enabled = True


def _router_app() -> FastAPI:
    app = FastAPI()
    for module in (playlists_module, podcasts_module, jobs_module, auth_module):
        app.include_router(module.router)
    app.dependency_overrides[get_current_user_id] = lambda: 1
    app.dependency_overrides[validate_csrf_token] = lambda: SESSION
    app.dependency_overrides[get_current_session] = lambda: SESSION
    return app


@pytest.fixture
def no_db_client():
    """Validation fails before the database is touched."""
    app = _router_app()

    async def no_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = no_db
    return TestClient(app)


@pytest_asyncio.fixture
async def maker():
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
        session.add(Playlist(user_id=1, name="Playlist", spotify_playlist_id=LINKED_ID))
        for n in (1, 2):
            session.add(Podcast(spotify_id=f"show{n}", name=f"Show {n}", total_episodes=0))
        await session.commit()
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(maker):
    app = _router_app()

    async def real_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = real_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


# --- Part 1: explicit nulls on PATCH /playlists/{id} ---


class TestExplicitNulls:
    @pytest.mark.parametrize("field", NON_NULLABLE)
    def test_schema_refuses_null(self, field):
        with pytest.raises(ValidationError, match=f"{field} cannot be null"):
            PlaylistUpdate.model_validate({field: None})

    @pytest.mark.parametrize("field", NON_NULLABLE)
    def test_patch_with_null_is_422(self, no_db_client, field):
        response = no_db_client.patch("/playlists/1", json={field: None})
        assert response.status_code == 422
        assert f"{field} cannot be null" in str(response.json()["detail"])

    def test_every_nulled_field_is_named(self):
        with pytest.raises(ValidationError, match="arrangement, name cannot be null"):
            PlaylistUpdate.model_validate({"name": None, "arrangement": None, "is_enabled": True})

    def test_null_spotify_playlist_id_is_allowed(self):
        update = PlaylistUpdate.model_validate({"spotify_playlist_id": None})
        assert "spotify_playlist_id" in update.model_fields_set
        assert update.spotify_playlist_id is None

    def test_absent_fields_are_fine(self):
        update = PlaylistUpdate.model_validate({})
        assert update.model_fields_set == set()

    def test_full_ios_body_validates(self):
        """The body iOS sends: every field, non-null, with a null link."""
        body = {
            "name": "Morning",
            "kind": "standard",
            "spotify_playlist_id": None,
            "is_enabled": True,
            "default_episode_limit": 0,
            "default_pick_from": "newest",
            "arrangement": "by_position",
            "date_direction": "oldest_first",
        }
        assert PlaylistUpdate.model_validate(body).spotify_playlist_id is None

    @pytest.mark.asyncio
    async def test_null_spotify_playlist_id_still_unlinks(self, client, maker):
        response = await client.patch("/playlists/1", json={"spotify_playlist_id": None})
        assert response.status_code == 200
        assert response.json()["spotify_playlist_id"] is None
        async with maker() as session:
            playlist = await session.get(Playlist, 1)
            assert playlist.spotify_playlist_id is None

    @pytest.mark.asyncio
    async def test_refused_patch_changes_nothing(self, client, maker):
        response = await client.patch("/playlists/1", json={"name": "New", "is_enabled": None})
        assert response.status_code == 422
        async with maker() as session:
            playlist = await session.get(Playlist, 1)
            assert playlist.name == "Playlist"
            assert playlist.is_enabled is True


# --- Part 2: response models ---


class TestOpenApiDocumentsResponses:
    @pytest.mark.parametrize(
        ("method", "path", "schema"),
        [
            ("post", "/playlists/{playlist_id}/run", "RunPlaylistResponse"),
            ("post", "/playlists/run-all", "RunAllPlaylistsResponse"),
            ("post", "/playlists/{playlist_id}/podcasts", "AddPodcastsResponse"),
            ("delete", "/playlists/{playlist_id}", "MessageResponse"),
            ("delete", "/playlists/{playlist_id}/podcasts/{podcast_id}", "MessageResponse"),
            ("put", "/playlists/{playlist_id}/podcasts/reorder", "MessageResponse"),
            ("post", "/podcasts/sync", "SyncResponse"),
            ("delete", "/podcasts/{podcast_id}", "MessageResponse"),
            ("get", "/jobs/status", "JobsStatusResponse"),
            ("put", "/jobs/schedule", "UpdateScheduleResponse"),
            ("delete", "/auth/me", "MessageResponse"),
            ("post", "/auth/logout", "MessageResponse"),
            ("get", "/auth/csrf-token", "CsrfTokenResponse"),
            ("get", "/auth/status", "AuthStatusResponse"),
        ],
    )
    def test_response_schema_is_a_model(self, method, path, schema):
        spec = _router_app().openapi()
        ok = spec["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert ok == {"$ref": f"#/components/schemas/{schema}"}

    def test_health_schema(self):
        spec = main_app.openapi()
        ok = spec["paths"]["/api/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert ok == {"$ref": "#/components/schemas/HealthResponse"}


def _fake_builder(monkeypatch, *, update=None, update_all=None):
    builder = MagicMock()
    builder.update_playlist = AsyncMock(return_value=update)
    builder.update_all_playlists = AsyncMock(return_value=update_all)
    monkeypatch.setattr(playlists_module, "PlaylistBuilder", MagicMock(return_value=builder))
    monkeypatch.setattr(playlists_module, "TokenManager", MagicMock())


class TestRunShapes:
    @pytest.mark.asyncio
    async def test_success_has_no_conditional_keys(self, client, monkeypatch):
        _fake_builder(monkeypatch, update=PlaylistUpdateResult(1, "Playlist", True, 4))
        body = (await client.post("/playlists/1/run")).json()
        assert body == {
            "message": "Playlist 'Playlist' updated successfully",
            "playlist_id": 1,
            "episode_count": 4,
        }

    @pytest.mark.asyncio
    async def test_partial_sends_partial_only(self, client, monkeypatch):
        result = PlaylistUpdateResult(1, "Playlist", False, 2, error="Show 2 failed", partial=True)
        _fake_builder(monkeypatch, update=result)
        body = (await client.post("/playlists/1/run")).json()
        assert body == {
            "message": "Playlist 'Playlist' updated with warnings: Show 2 failed",
            "playlist_id": 1,
            "episode_count": 2,
            "partial": True,
        }

    @pytest.mark.asyncio
    async def test_skipped_sends_skipped_only(self, client, monkeypatch):
        _fake_builder(monkeypatch, update=PlaylistUpdateResult(1, "Playlist", True, 0, skipped=True))
        body = (await client.post("/playlists/1/run")).json()
        assert body == {
            "message": "Playlist 'Playlist' is disabled and was left unchanged",
            "playlist_id": 1,
            "episode_count": 0,
            "skipped": True,
        }

    @pytest.mark.asyncio
    async def test_run_all(self, client, monkeypatch):
        results = [
            PlaylistUpdateResult(1, "A", True, 3),
            PlaylistUpdateResult(2, "B", False, 0, error="boom"),
        ]
        _fake_builder(monkeypatch, update_all=results)
        body = (await client.post("/playlists/run-all")).json()
        assert body == {
            "message": "Updated 1 playlists, 1 failed",
            "results": [
                {
                    "playlist_id": 1,
                    "playlist_name": "A",
                    "success": True,
                    "episode_count": 3,
                    "error": None,
                    "partial": False,
                    "skipped": False,
                },
                {
                    "playlist_id": 2,
                    "playlist_name": "B",
                    "success": False,
                    "episode_count": 0,
                    "error": "Failed to update playlist. Check the server logs for details.",
                    "partial": False,
                    "skipped": False,
                },
            ],
        }


class TestAssignmentShapes:
    @pytest.mark.asyncio
    async def test_add_reorder_remove(self, client):
        add = await client.post("/playlists/1/podcasts", json={"podcast_ids": [1, 2]})
        assert add.json() == {"message": "Added 2 podcast(s) to playlist", "added": 2}

        reorder = await client.put("/playlists/1/podcasts/reorder", json={"podcast_ids": [2, 1]})
        assert reorder.json() == {"message": "Podcasts reordered"}

        remove = await client.delete("/playlists/1/podcasts/1")
        assert remove.json() == {"message": "Podcast removed from playlist"}

    @pytest.mark.asyncio
    async def test_delete_playlist(self, client, maker):
        response = await client.delete("/playlists/1")
        assert response.json() == {"message": "Playlist deleted"}
        async with maker() as session:
            assert (await session.execute(select(PlaylistPodcast))).first() is None


class TestPodcastShapes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("reconciled", [True, False])
    async def test_sync(self, client, monkeypatch, reconciled):
        spotify = (MagicMock(), SimpleNamespace(force_refresh=AsyncMock()))
        monkeypatch.setattr(podcasts_module, "spotify_client", AsyncMock(return_value=spotify))
        result = LibrarySyncResult(synced=5, new=1, missing=0, removed=0, reconciled=reconciled)
        monkeypatch.setattr(podcasts_module, "sync_library", AsyncMock(return_value=result))
        body = (await client.post("/podcasts/sync")).json()
        assert body == {
            "message": "Sync completed",
            "synced": 5,
            "new": 1,
            "missing": 0,
            "removed": 0,
            "reconcile_skipped": not reconciled,
        }

    @pytest.mark.asyncio
    async def test_unfollow(self, client, monkeypatch):
        spotify = MagicMock(unfollow_show=AsyncMock())
        token_manager = SimpleNamespace(force_refresh=AsyncMock())
        monkeypatch.setattr(podcasts_module, "spotify_client", AsyncMock(return_value=(spotify, token_manager)))
        body = (await client.delete("/podcasts/1")).json()
        assert body == {"message": "Successfully unfollowed 'Show 1'"}


class TestJobShapes:
    def test_status_keeps_per_job_keys(self, no_db_client, monkeypatch):
        """Keys a job doesn't send stay out, as with the plain dict."""
        jobs = [
            {
                "id": "daily_playlist_update",
                "name": "Daily",
                "next_run": "2026-11-16T06:00:00+00:00",
                "last_run": None,
                "last_run_status": None,
                "type": "cron",
                "is_configurable": True,
                "schedule": {"hour": 6, "minute": 0},
                "schedule_times": [{"hour": 6, "minute": 0}, {"hour": 18, "minute": 30}],
                "schedule_timezone": "Europe/London",
                "max_schedule_times": 3,
                "last_run_failed_steps": ["library_sync"],
            },
            {
                "id": "token_refresh",
                "name": "Refresh",
                "next_run": None,
                "last_run": "2026-11-15T10:00:00+00:00",
                "last_run_status": None,
                "type": "interval",
                "is_configurable": False,
                "interval_minutes": 30,
            },
        ]
        monkeypatch.setattr(jobs_module, "get_job_status", AsyncMock(return_value=jobs))
        assert no_db_client.get("/jobs/status").json() == {"jobs": jobs}

    def test_schedule(self, no_db_client, monkeypatch):
        reschedule = AsyncMock(return_value="2026-11-16T06:00:00+00:00")
        monkeypatch.setattr(jobs_module, "reschedule_playlist_update", reschedule)
        body = no_db_client.put("/jobs/schedule", json={"times": [{"hour": 6, "minute": 0}]}).json()
        assert body == {"message": "Schedule updated", "next_run": "2026-11-16T06:00:00+00:00"}


class TestAuthShapes:
    def test_csrf_token(self, no_db_client):
        assert no_db_client.get("/auth/csrf-token").json() == {"csrf_token": "csrf"}

    def test_status_without_cookie(self, no_db_client):
        assert no_db_client.get("/auth/status").json() == {"authenticated": False}

    def test_health(self):
        body = TestClient(main_app).get("/api/health").json()
        assert set(body) == {"status", "app", "version", "commit"}
        assert body["status"] == "healthy"
