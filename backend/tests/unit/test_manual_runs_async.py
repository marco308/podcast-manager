"""Async manual runs and the run history endpoints (issues #242, #246).

``POST /playlists/{id}/run`` and ``/run-all`` with ``Prefer: respond-async``
take the write lock in the request, answer 202 with a SyncLog run id, and
carry on in a background task that owns the lock until it is done. Without
the header they stay synchronous (installed iOS builds rely on that; the
response shapes are pinned in ``test_api_contract_issue310.py``).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.jobs import locks, manual_run
from app.models import Playlist, Session, SyncLog, User
from app.models.sync_log import SyncStatus
from app.rate_limit import limiter
from app.routers import auth as auth_module
from app.routers import jobs as jobs_module
from app.routers import playlists as playlists_module
from app.routers.auth import get_current_session, get_current_user_id, validate_csrf_token
from app.services.encryption import TokenDecryptionError
from app.services.playlist_builder import PlaylistUpdateResult
from tests.job_patches import patch_job_sessions

SESSION = SimpleNamespace(user_id=1, csrf_token="csrf")
ASYNC = {"Prefer": "respond-async"}


@pytest.fixture(autouse=True)
def _fresh_locks(monkeypatch):
    """Fresh locks and gate per test — asyncio primitives bind to the running loop."""
    monkeypatch.setattr(locks, "playlist_write_lock", asyncio.Lock())
    monkeypatch.setattr(locks, "library_sync_lock", asyncio.Lock())
    monkeypatch.setattr(locks, "account_write_gate", locks.AccountWriteGate())
    monkeypatch.setattr(playlists_module, "WRITE_LOCK_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(auth_module, "ACCOUNT_DELETE_LOCK_WAIT_SECONDS", 0.05)


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
        session.add(Playlist(user_id=1, name="Commute", spotify_playlist_id="sp1"))
        session.add(Playlist(user_id=1, name="Off", spotify_playlist_id="sp2", is_enabled=False))
        session.add(
            Session(
                session_id_hash="hash",
                user_id=1,
                csrf_token="csrf",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
    try:
        with patch_job_sessions(maker):
            yield maker
    finally:
        # A test that failed mid-run must not leave a task behind.
        for task in list(manual_run._background_runs):
            task.cancel()
        await engine.dispose()


@pytest_asyncio.fixture
async def client(maker):
    app = FastAPI()
    for module in (playlists_module, jobs_module, auth_module):
        app.include_router(module.router)
    app.dependency_overrides[get_current_user_id] = lambda: 1
    app.dependency_overrides[validate_csrf_token] = lambda: SESSION
    app.dependency_overrides[get_current_session] = lambda: SESSION

    async def real_db():
        async with maker() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = real_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


class GatedBuilder:
    """Stands in for PlaylistBuilder in the background task; holds each build
    until ``release`` is set, so a test can look at the run mid-flight."""

    def __init__(self, result=None, results=None, error: BaseException | None = None):
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.result = result
        self.results = results
        self.error = error

    def __call__(self, *args, **kwargs):
        return self

    async def _wait(self):
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error

    async def update_playlist(self, playlist):
        await self._wait()
        return self.result or PlaylistUpdateResult(playlist.id, playlist.name, True, 4)

    async def update_all_playlists(self):
        await self._wait()
        return self.results or []


@pytest.fixture
def builder(monkeypatch):
    fake = GatedBuilder()
    monkeypatch.setattr(manual_run, "PlaylistBuilder", fake)
    monkeypatch.setattr(manual_run, "TokenManager", MagicMock())
    return fake


async def _finish(builder: GatedBuilder) -> None:
    builder.release.set()
    await asyncio.wait_for(asyncio.gather(*list(manual_run._background_runs)), 2)


async def _rows(maker) -> list[SyncLog]:
    async with maker() as db:
        return list((await db.execute(select(SyncLog).order_by(SyncLog.id))).scalars().all())


class TestAsyncRun:
    @pytest.mark.asyncio
    async def test_202_holds_the_lock_until_the_background_run_ends(self, client, maker, builder):
        response = await client.post("/playlists/1/run", headers=ASYNC)

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "running"
        run_id = body["run_id"]
        assert response.headers["location"] == f"/api/jobs/runs/{run_id}"
        assert response.headers["preference-applied"] == "respond-async"
        # The lock was taken in the request and is still held: there is no
        # gap between the 202 and the task for another writer to slip into.
        assert locks.playlist_write_lock.locked()
        assert (await client.get(f"/jobs/runs/{run_id}")).json()["status"] == "running"

        await _finish(builder)

        assert not locks.playlist_write_lock.locked()
        polled = (await client.get(f"/jobs/runs/{run_id}")).json()
        assert polled["status"] == "success"
        assert polled["job_type"] == "manual_playlist_update"
        assert polled["failure_code"] is None
        assert polled["message"] == "Playlist 'Commute' updated successfully"
        assert polled["results"] == [
            {
                "playlist_id": 1,
                "playlist_name": "Commute",
                "success": True,
                "episode_count": 4,
                "error": None,
                "partial": False,
                "skipped": False,
            }
        ]
        assert (polled["playlists_attempted"], polled["playlists_failed"]) == (1, 0)

    @pytest.mark.asyncio
    async def test_lock_held_is_still_a_409_and_records_nothing(self, client, maker, builder):
        await locks.playlist_write_lock.acquire()
        try:
            response = await client.post("/playlists/1/run", headers=ASYNC)
        finally:
            locks.playlist_write_lock.release()

        assert response.status_code == 409
        assert await _rows(maker) == []

    @pytest.mark.asyncio
    async def test_disabled_playlist_is_still_a_409(self, client, maker, builder):
        response = await client.post("/playlists/2/run", headers=ASYNC)

        assert response.status_code == 409
        assert "disabled" in response.json()["detail"].lower()
        assert not locks.playlist_write_lock.locked()
        assert await _rows(maker) == []

    @pytest.mark.asyncio
    async def test_second_run_while_one_is_in_flight_is_a_409(self, client, maker, builder):
        first = await client.post("/playlists/1/run", headers=ASYNC)
        second = await client.post("/playlists/run-all", headers=ASYNC)
        sync = await client.post("/playlists/1/run")

        assert first.status_code == 202
        assert second.status_code == 409
        assert sync.status_code == 409
        await _finish(builder)
        assert [row.status for row in await _rows(maker)] == [SyncStatus.SUCCESS]

    @pytest.mark.asyncio
    async def test_a_crashing_run_is_finalised_failed_and_frees_the_lock(self, client, maker, builder):
        builder.error = RuntimeError("boom")

        run_id = (await client.post("/playlists/1/run", headers=ASYNC)).json()["run_id"]
        await _finish(builder)

        assert not locks.playlist_write_lock.locked()
        polled = (await client.get(f"/jobs/runs/{run_id}")).json()
        assert polled["status"] == "failed"
        assert polled["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_partial_run_is_reported_as_partial(self, client, maker, builder):
        builder.result = PlaylistUpdateResult(1, "Commute", False, 2, error="Show 2 failed", partial=True)

        run_id = (await client.post("/playlists/1/run", headers=ASYNC)).json()["run_id"]
        await _finish(builder)

        polled = (await client.get(f"/jobs/runs/{run_id}")).json()
        assert polled["failure_code"] == "partial"
        assert polled["message"] == "Playlist 'Commute' updated with warnings: Show 2 failed"
        assert polled["results"][0]["partial"] is True

    @pytest.mark.asyncio
    async def test_failure_hides_the_exception_text(self, client, maker, builder):
        builder.result = PlaylistUpdateResult(
            1, "Commute", False, 0, error="secret detail", exception=RuntimeError("secret detail")
        )

        run_id = (await client.post("/playlists/1/run", headers=ASYNC)).json()["run_id"]
        await _finish(builder)

        polled = (await client.get(f"/jobs/runs/{run_id}")).json()
        assert polled["status"] == "failed"
        assert polled["message"] == manual_run.GENERIC_FAILURE
        assert polled["results"][0]["error"] == manual_run.GENERIC_FAILURE

    @pytest.mark.asyncio
    async def test_unreadable_credentials_say_sign_in_again(self, client, maker, builder):
        """The request has already answered, so it can't sign the client out;
        the run records ``credentials_unreadable`` for the client to act on."""
        error = TokenDecryptionError("bad key")
        builder.result = PlaylistUpdateResult(1, "Commute", False, 0, error=str(error), exception=error)

        run_id = (await client.post("/playlists/1/run", headers=ASYNC)).json()["run_id"]
        await _finish(builder)

        polled = (await client.get(f"/jobs/runs/{run_id}")).json()
        assert polled["status"] == "failed"
        assert polled["failure_code"] == "credentials_unreadable"
        assert "sign in again" in polled["message"].lower()

    @pytest.mark.asyncio
    async def test_run_all(self, client, maker, builder):
        builder.results = [
            PlaylistUpdateResult(1, "Commute", True, 3),
            PlaylistUpdateResult(3, "Other", False, 0, error="boom", exception=RuntimeError("boom")),
        ]

        response = await client.post("/playlists/run-all", headers=ASYNC)
        assert response.status_code == 202
        assert locks.playlist_write_lock.locked()
        await _finish(builder)

        polled = (await client.get(f"/jobs/runs/{response.json()['run_id']}")).json()
        assert polled["status"] == "failed"
        assert polled["message"] == "Updated 1 playlists, 1 failed"
        assert [r["success"] for r in polled["results"]] == [True, False]
        assert (polled["playlists_attempted"], polled["playlists_failed"]) == (2, 1)

    @pytest.mark.asyncio
    async def test_without_the_header_the_run_stays_synchronous_and_is_recorded(self, client, maker, monkeypatch):
        builder = MagicMock()
        builder.update_playlist = AsyncMock(return_value=PlaylistUpdateResult(1, "Commute", True, 4))
        monkeypatch.setattr(playlists_module, "PlaylistBuilder", MagicMock(return_value=builder))
        monkeypatch.setattr(playlists_module, "TokenManager", MagicMock())

        response = await client.post("/playlists/1/run")

        assert response.status_code == 200
        assert response.json() == {
            "message": "Playlist 'Commute' updated successfully",
            "playlist_id": 1,
            "episode_count": 4,
        }
        assert not manual_run._background_runs
        [row] = await _rows(maker)
        assert (row.job_type, row.status) == ("manual_playlist_update", SyncStatus.SUCCESS)


class TestAccountDeletionWaitsForBackgroundRun:
    """The write gate only covers a request while it runs; an async run
    outlives its request. It holds ``playlist_write_lock`` instead, which the
    delete also takes — so the delete is a 409 until the run is done."""

    @pytest.mark.asyncio
    async def test_delete_is_a_409_while_a_run_is_in_flight(self, client, maker, builder):
        assert (await client.post("/playlists/1/run", headers=ASYNC)).status_code == 202
        await builder.started.wait()

        async with maker() as db:
            with pytest.raises(HTTPException) as exc_info:
                await auth_module.delete_me(response=Response(), session=SESSION, db=db)
        assert exc_info.value.status_code == 409

        async with maker() as db:
            assert (await db.execute(select(func.count()).select_from(User))).scalar_one() == 1
        # The refused delete released what it took and left the run's lock alone.
        assert locks.playlist_write_lock.locked()
        assert not locks.library_sync_lock.locked()

        await _finish(builder)

        async with maker() as db:
            await auth_module.delete_me(response=Response(), session=SESSION, db=db)
            assert (await db.execute(select(func.count()).select_from(User))).scalar_one() == 0


class TestRunHistory:
    @staticmethod
    async def _seed(maker):
        now = datetime.now(UTC)
        async with maker() as db:
            for minutes, job_type, status in [
                (30, "playlist_update", SyncStatus.SUCCESS),
                (20, "cleanup", SyncStatus.FAILED),
                (10, "playlist_update", SyncStatus.FAILED),
            ]:
                db.add(
                    SyncLog(
                        job_type=job_type,
                        status=status,
                        started_at=now - timedelta(minutes=minutes),
                        completed_at=now - timedelta(minutes=minutes - 1),
                        failure_code="rate_limit" if status == SyncStatus.FAILED else None,
                        playlists_attempted=2,
                        playlists_failed=1 if status == SyncStatus.FAILED else 0,
                    )
                )
            await db.commit()

    @pytest.mark.asyncio
    async def test_newest_first(self, client, maker):
        await self._seed(maker)
        runs = (await client.get("/jobs/runs")).json()["runs"]
        assert [r["job_type"] for r in runs] == ["playlist_update", "cleanup", "playlist_update"]
        assert runs[0]["failure_code"] == "rate_limit"
        assert runs[0]["message"] is None and runs[0]["results"] is None

    @pytest.mark.asyncio
    async def test_filter_and_limit(self, client, maker):
        await self._seed(maker)
        runs = (await client.get("/jobs/runs", params={"job_type": "playlist_update", "limit": 1})).json()["runs"]
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [0, 101])
    async def test_limit_is_bounded(self, client, limit):
        assert (await client.get("/jobs/runs", params={"limit": limit})).status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_run_is_a_404(self, client):
        assert (await client.get("/jobs/runs/999")).status_code == 404
