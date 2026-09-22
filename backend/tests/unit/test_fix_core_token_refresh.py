"""Unit tests for the ``token_refresh`` job's refresh semantics.

Issues #166 and #167.

#166 — the job's refresh threshold used to be 900s against a 45-minute
``IntervalTrigger``. A 60-minute Spotify token refreshed at J0 still has
~15 minutes of life at J0+45, so the run skipped it; the token then died
at J0+60 and nothing touched it until J0+90. Net effect: the stored access
token was expired for ~30 minutes out of every 90, and the endpoints that
use the raw stored token (rather than TokenManager) 500'd throughout.
The threshold must therefore always exceed the job interval.

#167 — the job used to snapshot each user's encrypted refresh token in a
read phase, call Spotify in a write phase, and blind-write the result,
bypassing ``TokenManager``'s per-user lock. Spotify rotates the refresh
token on every successful ``POST /api/token``, so a concurrent
TokenManager refresh (the daily rebuild refreshes at every write
boundary) and this job could both spend RT1; last-write-wins then leaves
a superseded refresh token in the DB and the next refresh fails
``invalid_grant``. The job must go through ``TokenManager``, which
re-reads the refresh token *inside* the lock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jobs import scheduler
from app.services.token_manager import TokenManager


class _FakeResult:
    """Minimal stand-in for a SQLAlchemy ``Result``."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Async-context-manager session returning a fixed row set."""

    def __init__(self, rows: list, *, raises: Exception | None = None) -> None:
        self._rows = rows
        self._raises = raises

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, _stmt):
        if self._raises is not None:
            raise self._raises
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        return None


def _scheduler_session_factory(user_ids: list[int], *, raises: Exception | None = None):
    """Fake ``async_session_maker`` for the job's ``select(User.id)`` read."""

    def _make() -> _FakeSession:
        return _FakeSession([(uid,) for uid in user_ids], raises=raises)

    return _make


@pytest.fixture(autouse=True)
def _clear_locks():
    """Reset TokenManager's class-level lock registry between tests."""
    TokenManager._user_locks.clear()
    yield
    TokenManager._user_locks.clear()


# --------------------------------------------------------------------------
# Issue #166 — threshold must outlive the interval
# --------------------------------------------------------------------------


def test_refresh_threshold_exceeds_job_interval():
    """The invariant from #166, asserted directly on the constants.

    If the threshold ever drops to (or below) the interval, a token can
    expire in the gap between two runs.
    """
    interval_seconds = scheduler.TOKEN_REFRESH_INTERVAL_MINUTES * 60
    assert interval_seconds < scheduler.TOKEN_REFRESH_THRESHOLD_SECONDS, (
        "refresh threshold must exceed the job interval or tokens die between runs"
    )


def test_refresh_threshold_covers_the_old_dead_window():
    """The specific regression: 900s was the broken value, 3000s is the fix."""
    assert scheduler.TOKEN_REFRESH_THRESHOLD_SECONDS == 3000
    # A token with 40 minutes left — skipped by the old 900s threshold,
    # dead before the next run — is now inside the refresh window.
    assert scheduler.TOKEN_REFRESH_THRESHOLD_SECONDS > 40 * 60


@pytest.mark.asyncio
async def test_job_asks_token_manager_for_the_full_threshold():
    """``get_token`` must be called with the interval-derived threshold."""
    get_token = AsyncMock(return_value="fresh-access")
    manager = MagicMock()
    manager.get_token = get_token

    with (
        patch("app.jobs.scheduler.async_session_maker", _scheduler_session_factory([1])),
        patch("app.jobs.scheduler.TokenManager", return_value=manager) as ctor,
    ):
        await scheduler.refresh_all_tokens()

    ctor.assert_called_once_with(1)
    get_token.assert_awaited_once_with(min_remaining_seconds=scheduler.TOKEN_REFRESH_THRESHOLD_SECONDS)


@pytest.mark.asyncio
async def test_token_with_forty_minutes_left_is_actually_refreshed():
    """End-to-end through the real TokenManager: 40 minutes left ⇒ refresh.

    This is the #166 regression in behavioural form — under the old 900s
    threshold this user was skipped and their token expired 20 minutes
    later.
    """
    user = MagicMock()
    user.id = 1
    user.access_token = "enc:cached-access"
    user.refresh_token = "enc:cached-refresh"
    user.token_expires_at = datetime.now(UTC) + timedelta(minutes=40)

    encryption = MagicMock()
    encryption.decrypt.side_effect = lambda c: c.removeprefix("enc:")
    encryption.encrypt.side_effect = lambda p: f"enc:{p}"

    refresh = AsyncMock(
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        }
    )

    def _tm_session_factory() -> _FakeSession:
        return _FakeSession([user])

    with (
        patch("app.jobs.scheduler.async_session_maker", _scheduler_session_factory([1])),
        patch("app.services.token_manager.async_session_maker", _tm_session_factory),
        patch("app.services.token_manager.get_encryption_service", return_value=encryption),
        patch("app.services.token_manager.SpotifyService.refresh_access_token", refresh),
    ):
        await scheduler.refresh_all_tokens()

    refresh.assert_awaited_once_with("cached-refresh")
    assert user.access_token == "enc:new-access"
    assert user.refresh_token == "enc:new-refresh"


@pytest.mark.asyncio
async def test_token_with_ample_life_is_left_alone():
    """A token well clear of the threshold must not be refreshed.

    Guards the other direction: raising the threshold must not turn the
    job into "refresh everything on every run", which would rotate the
    refresh token far more often than necessary.
    """
    user = MagicMock()
    user.id = 1
    user.access_token = "enc:cached-access"
    user.refresh_token = "enc:cached-refresh"
    user.token_expires_at = datetime.now(UTC) + timedelta(minutes=55)

    encryption = MagicMock()
    encryption.decrypt.side_effect = lambda c: c.removeprefix("enc:")
    encryption.encrypt.side_effect = lambda p: f"enc:{p}"

    refresh = AsyncMock()

    def _tm_session_factory() -> _FakeSession:
        return _FakeSession([user])

    with (
        patch("app.jobs.scheduler.async_session_maker", _scheduler_session_factory([1])),
        patch("app.services.token_manager.async_session_maker", _tm_session_factory),
        patch("app.services.token_manager.get_encryption_service", return_value=encryption),
        patch("app.services.token_manager.SpotifyService.refresh_access_token", refresh),
    ):
        await scheduler.refresh_all_tokens()

    refresh.assert_not_awaited()


# --------------------------------------------------------------------------
# Issue #167 — no hand-rolled refresh outside the per-user lock
# --------------------------------------------------------------------------


def test_job_module_no_longer_imports_the_encryption_service():
    """The hand-rolled path needed ``get_encryption_service`` to decrypt the
    snapshotted refresh token. Nothing in the scheduler should decrypt
    tokens any more — that belongs to TokenManager, under the lock."""
    assert not hasattr(scheduler, "get_encryption_service"), (
        "scheduler must not decrypt tokens itself; route refreshes through TokenManager (#167)"
    )


@pytest.mark.asyncio
async def test_job_never_calls_spotify_refresh_directly():
    """The job must not touch ``SpotifyService.refresh_access_token``.

    Calling it from the job body is the bypass: it happens outside
    ``TokenManager._lock_for(user_id)`` and against a refresh token read
    before the lock was ever taken.
    """
    get_token = AsyncMock(return_value="fresh-access")
    manager = MagicMock()
    manager.get_token = get_token
    direct_refresh = AsyncMock()

    with (
        patch("app.jobs.scheduler.async_session_maker", _scheduler_session_factory([1, 2])),
        patch("app.jobs.scheduler.TokenManager", return_value=manager),
        patch("app.services.spotify.SpotifyService.refresh_access_token", direct_refresh),
    ):
        await scheduler.refresh_all_tokens()

    direct_refresh.assert_not_awaited()
    assert get_token.await_count == 2


@pytest.mark.asyncio
async def test_refresh_holds_the_per_user_lock_for_the_whole_refresh():
    """A concurrent TokenManager caller must not be able to refresh in
    parallel with the job — the lock is what stops the rotation race.

    We assert the job's refresh runs with the per-user lock held, so the
    refresh token it spends was read inside that lock rather than
    snapshotted beforehand.
    """
    user = MagicMock()
    user.id = 1
    user.access_token = "enc:cached-access"
    user.refresh_token = "enc:cached-refresh"
    user.token_expires_at = datetime.now(UTC) + timedelta(minutes=10)

    encryption = MagicMock()
    encryption.decrypt.side_effect = lambda c: c.removeprefix("enc:")
    encryption.encrypt.side_effect = lambda p: f"enc:{p}"

    lock_held_during_refresh: list[bool] = []

    async def _refresh(_rt: str) -> dict:
        lock_held_during_refresh.append(TokenManager._lock_for(1).locked())
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        }

    def _tm_session_factory() -> _FakeSession:
        return _FakeSession([user])

    with (
        patch("app.jobs.scheduler.async_session_maker", _scheduler_session_factory([1])),
        patch("app.services.token_manager.async_session_maker", _tm_session_factory),
        patch("app.services.token_manager.get_encryption_service", return_value=encryption),
        patch("app.services.token_manager.SpotifyService.refresh_access_token", side_effect=_refresh),
    ):
        await scheduler.refresh_all_tokens()

    assert lock_held_during_refresh == [True], "the refresh must happen under the per-user lock (#167)"


@pytest.mark.asyncio
async def test_one_user_failing_does_not_abort_the_rest():
    """A per-user refresh failure must be logged and stepped over."""
    seen: list[int] = []

    class _Manager:
        def __init__(self, user_id: int) -> None:
            self._user_id = user_id

        async def get_token(self, *, min_remaining_seconds: int) -> str:
            seen.append(self._user_id)
            if self._user_id == 2:
                raise RuntimeError("user 2 is broken")
            return "fresh-access"

    with (
        patch("app.jobs.scheduler.async_session_maker", _scheduler_session_factory([1, 2, 3])),
        patch("app.jobs.scheduler.TokenManager", _Manager),
    ):
        await scheduler.refresh_all_tokens()

    assert seen == [1, 2, 3], "a failing user must not stop the job"


@pytest.mark.asyncio
async def test_db_read_failure_ends_the_job_quietly():
    """If the user-id read fails there is nothing to refresh — and no
    SyncLog row to orphan, so a plain return is correct here."""
    manager = MagicMock()
    manager.get_token = AsyncMock()

    with (
        patch(
            "app.jobs.scheduler.async_session_maker",
            _scheduler_session_factory([1], raises=RuntimeError("db down")),
        ),
        patch("app.jobs.scheduler.TokenManager", return_value=manager),
    ):
        await scheduler.refresh_all_tokens()

    manager.get_token.assert_not_awaited()
