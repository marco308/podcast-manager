"""Integration tests for the cleanup vs. rebuild write-lock interaction.

Issue #89, PR3. The cleanup job and the rebuild job both issue Spotify
writes against the same playlists — without serialisation they race
and produce the half-rebuilt / half-cleaned state from the bug.

These tests verify:

  - cleanup waits on the shared :data:`playlist_write_lock` if rebuild
    is holding it
  - cleanup skips entirely (no lock acquisition, no Spotify client)
    when a successful rebuild completed in the last 60 minutes
  - cleanup runs normally when the most recent rebuild is older than
    the 60-minute window
  - the manual ``/playlists/run-all`` endpoint handler takes the same
    lock — so a button-press serialises against scheduled work

The cleanup function pulls a fair amount of context (users, playlists,
SpotifyService, TokenManager) — rather than spin up real DB rows we
monkeypatch the boundaries it touches. This keeps each test under a
few hundred ms and lets us assert "SpotifyService was never
instantiated" with a counter.

All tests reset ``locks.playlist_write_lock`` to a fresh
:class:`asyncio.Lock` in a fixture so state can't leak between cases
(``asyncio.Lock`` is bound to the running event loop, and pytest-asyncio
gives each test its own loop).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jobs import locks, scheduler
from app.models.sync_log import SyncStatus


@pytest.fixture(autouse=True)
def _fresh_lock():
    """Give each test a clean lock bound to the current event loop.

    ``asyncio.Lock`` instances are tied to the loop that first awaits
    them. pytest-asyncio creates a fresh loop per test, so reusing the
    module-level lock across tests can produce "attached to a different
    loop" errors. Resetting here keeps each test isolated.
    """
    original = locks.playlist_write_lock
    locks.playlist_write_lock = asyncio.Lock()
    try:
        yield
    finally:
        locks.playlist_write_lock = original


def _make_session_factory(*, recent_rebuild_at: datetime | None, users: list = None):
    """Build a fake ``async_session_maker`` returning a session that:

    - returns ``recent_rebuild_at`` (or None) for the recency-gate query,
      but only if the timestamp falls within the 60-minute window — the
      production query has ``WHERE completed_at > NOW() - 60min`` and we
      mimic that here so tests can pass a "stale" timestamp and observe
      the gate let cleanup through.
    - returns ``users`` for the User enumeration
    - swallows commit / add silently
    """
    users = users or []
    cutoff = datetime.now(UTC) - scheduler.CLEANUP_RECENCY_WINDOW
    gate_row = recent_rebuild_at if (recent_rebuild_at is not None and recent_rebuild_at > cutoff) else None

    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def scalars(self):
            inner = self._value if isinstance(self._value, list) else []
            r = MagicMock()
            r.all.return_value = inner
            return r

        def all(self):
            return self._value if isinstance(self._value, list) else []

    class _FakeSession:
        def __init__(self):
            self._next: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def execute(self, stmt):
            # Dispatch by matching on the FROM table name in the stringified
            # SQL. Anchoring on " from <table>" avoids the trap where a bare
            # "user" substring also matches playlist queries via
            # ``playlists.user_id``.
            sql = str(stmt).lower()
            if " from sync_logs" in sql:
                if gate_row is not None:
                    row = MagicMock()
                    row.completed_at = gate_row
                    row.status = SyncStatus.SUCCESS
                    row.job_type = "playlist_update"
                    return _FakeResult(row)
                return _FakeResult(None)
            if " from playlists" in sql:
                return _FakeResult([])
            if " from users" in sql:
                return _FakeResult(users)
            return _FakeResult(None)

        async def commit(self):
            return None

        async def rollback(self):
            return None

        def add(self, _obj):
            return None

    def factory():
        return _FakeSession()

    return factory


@pytest.mark.asyncio
async def test_cleanup_waits_for_rebuild_lock():
    """Cleanup must not begin its write phase until rebuild releases the lock."""
    events: list[str] = []

    async def fake_rebuild_holding_lock():
        """Stand in for ``update_all_playlists`` — grabs the lock and holds."""
        async with locks.playlist_write_lock:
            events.append("rebuild_acquired")
            await asyncio.sleep(0.2)
            events.append("rebuild_released")

    # Patch out everything cleanup touches past the recency gate. The
    # recency gate returns None (no recent rebuild), so we proceed to
    # the lock.
    session_factory = _make_session_factory(recent_rebuild_at=None, users=[])

    with patch("app.jobs.scheduler.async_session_maker", session_factory):
        rebuild_task = asyncio.create_task(fake_rebuild_holding_lock())
        # Yield so the rebuild task actually starts and takes the lock
        # before cleanup begins.
        await asyncio.sleep(0.01)
        assert locks.playlist_write_lock.locked(), "rebuild should hold the lock"

        async def cleanup_then_record():
            await scheduler.remove_played_episodes_from_playlists()
            events.append("cleanup_done")

        cleanup_task = asyncio.create_task(cleanup_then_record())
        await asyncio.gather(rebuild_task, cleanup_task)

    # Cleanup must not finish before rebuild released the lock.
    assert events.index("rebuild_released") < events.index("cleanup_done"), (
        f"cleanup completed before rebuild released the lock: {events}"
    )


@pytest.mark.asyncio
async def test_cleanup_skips_when_rebuild_recent():
    """A successful rebuild within the last 60min short-circuits cleanup."""
    recent = datetime.now(UTC) - timedelta(minutes=30)
    session_factory = _make_session_factory(recent_rebuild_at=recent, users=[])

    spotify_instances = 0

    def _spotify_ctor(*_a, **_kw):
        nonlocal spotify_instances
        spotify_instances += 1
        return MagicMock()

    with (
        patch("app.jobs.scheduler.async_session_maker", session_factory),
        patch("app.jobs.scheduler.SpotifyService", side_effect=_spotify_ctor),
    ):
        await scheduler.remove_played_episodes_from_playlists()

    assert spotify_instances == 0, (
        "cleanup must short-circuit before instantiating SpotifyService"
    )
    assert not locks.playlist_write_lock.locked(), (
        "cleanup must not have acquired the write lock"
    )


@pytest.mark.asyncio
async def test_cleanup_runs_when_rebuild_stale():
    """A rebuild from >60min ago does not gate cleanup — it proceeds normally."""
    stale = datetime.now(UTC) - timedelta(minutes=90)
    session_factory = _make_session_factory(recent_rebuild_at=stale, users=[])

    spotify_instances = 0

    def _spotify_ctor(*_a, **_kw):
        nonlocal spotify_instances
        spotify_instances += 1
        client = MagicMock()
        client.api_calls_used = 0
        client.reset_api_counter = MagicMock()
        return client

    lock_acquired_during_run = False

    original_acquire = locks.playlist_write_lock.acquire

    async def _spy_acquire():
        nonlocal lock_acquired_during_run
        lock_acquired_during_run = True
        return await original_acquire()

    with (
        patch("app.jobs.scheduler.async_session_maker", session_factory),
        patch("app.jobs.scheduler.SpotifyService", side_effect=_spotify_ctor),
        patch.object(locks.playlist_write_lock, "acquire", _spy_acquire),
    ):
        await scheduler.remove_played_episodes_from_playlists()

    assert lock_acquired_during_run, (
        "cleanup should have taken the write lock past the stale gate"
    )
    # No users / playlists in our fake DB → SpotifyService isn't built,
    # but we did get past the recency gate. The lock acquisition above
    # is the operative assertion.


@pytest.mark.asyncio
async def test_manual_run_takes_same_lock():
    """The /playlists/run-all handler must wait on the same lock cleanup holds.

    We invoke the underlying handler function directly via the slowapi
    rate-limiter's ``__wrapped__`` attribute — that bypasses the
    Depends/CSRF/rate-limit plumbing without losing the lock logic
    we care about. (Calling the limiter-decorated function would
    demand a real ``starlette.requests.Request``.)
    """
    from app.routers import playlists as playlists_router

    # The @limiter.limit decorator wraps the original handler; unwrap.
    handler = getattr(
        playlists_router.run_all_playlist_updates, "__wrapped__",
        playlists_router.run_all_playlist_updates,
    )

    events: list[str] = []

    async def fake_cleanup_holding_lock():
        async with locks.playlist_write_lock:
            events.append("cleanup_acquired")
            await asyncio.sleep(0.2)
            events.append("cleanup_released")

    user = MagicMock()
    user.id = 7

    fake_db = MagicMock()

    async def _exec(_stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = user
        return r

    fake_db.execute = AsyncMock(side_effect=_exec)
    # The handler commits explicitly before returning (issue #182: get_db's
    # post-yield commit runs *after* the response is sent), so the fake
    # session needs an awaitable commit.
    fake_db.commit = AsyncMock()

    # PlaylistBuilder.update_all_playlists must wait on the lock — we
    # tag the order it actually fires in.
    async def _fake_update_all(self):
        events.append("manual_update_ran")
        return []

    with patch(
        "app.routers.playlists.PlaylistBuilder.update_all_playlists",
        _fake_update_all,
    ):
        cleanup_task = asyncio.create_task(fake_cleanup_holding_lock())
        await asyncio.sleep(0.01)
        assert locks.playlist_write_lock.locked()

        manual_task = asyncio.create_task(
            handler(
                request=MagicMock(),
                session=MagicMock(user_id=user.id),
                db=fake_db,
            )
        )

        await asyncio.gather(cleanup_task, manual_task)

    # The manual run's actual update_all_playlists call must come AFTER
    # cleanup released the lock.
    assert events.index("cleanup_released") < events.index("manual_update_ran"), (
        f"manual run executed before cleanup released the lock: {events}"
    )


@pytest.mark.asyncio
async def test_manual_run_returns_409_when_lock_is_held_too_long():
    """A long-held lock must produce a 409, not a request that hangs.

    Issue #153: the manual endpoints used to await the lock unbounded, so a
    multi-minute rebuild left the caller blocked well past nginx's 30s
    proxy_read_timeout. Now they give up after WRITE_LOCK_WAIT_SECONDS.
    """
    from fastapi import HTTPException

    from app.routers import playlists as playlists_router

    handler = getattr(
        playlists_router.run_all_playlist_updates,
        "__wrapped__",
        playlists_router.run_all_playlist_updates,
    )

    user = MagicMock()
    user.id = 7

    fake_db = MagicMock()

    async def _exec(_stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = user
        return r

    fake_db.execute = AsyncMock(side_effect=_exec)
    # Not reached on the 409 path (the lock acquire raises first), but keeps
    # this fake in step with the handler's explicit commit.
    fake_db.commit = AsyncMock()

    ran = False

    async def _fake_update_all(self):
        nonlocal ran
        ran = True
        return []

    async def hold_lock_forever(release: asyncio.Event):
        async with locks.playlist_write_lock:
            await release.wait()

    release = asyncio.Event()
    holder = asyncio.create_task(hold_lock_forever(release))
    await asyncio.sleep(0.01)
    assert locks.playlist_write_lock.locked()

    with (
        patch("app.routers.playlists.PlaylistBuilder.update_all_playlists", _fake_update_all),
        patch("app.routers.playlists.WRITE_LOCK_WAIT_SECONDS", 0.05),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await handler(
                request=MagicMock(),
                session=MagicMock(user_id=user.id),
                db=fake_db,
            )

    assert exc_info.value.status_code == 409
    assert not ran, "the update must not run when the lock could not be acquired"

    release.set()
    await asyncio.wait_for(holder, timeout=1)

    # The failed acquire must not have left the lock in a broken state.
    assert not locks.playlist_write_lock.locked()
    async with locks.playlist_write_lock:
        pass
