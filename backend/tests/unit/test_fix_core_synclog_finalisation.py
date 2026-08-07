"""Unit tests: background jobs must never orphan a RUNNING SyncLog row.

Issue #174. Both long-running jobs write a ``RUNNING`` SyncLog row before
they start and finalise it at the end. Two paths used to skip the
finalisation entirely:

  - ``update_all_playlists`` did a bare ``return`` when the user read
    failed, leaving the row it had just created stuck ``RUNNING``.
  - the cleanup job caught only ``RuntimeError`` around
    ``TokenManager.get_token``; a ``TokenDecryptionError`` or an httpx
    error from the refresh path escaped the whole job body, so
    ``_finalise_cleanup_log`` never ran.

Permanently-RUNNING rows accumulate in the history the UI shows and
record nothing about what actually went wrong. Every exit path must
finalise with ``FAILED`` plus the error detail.

These tests assert on the finalisation helpers rather than on DB state:
the helpers are the single choke point both jobs must reach.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jobs import locks, scheduler
from app.models.sync_log import SyncStatus


class _FakeResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        inner = self._value if isinstance(self._value, list) else []
        r = MagicMock()
        r.all.return_value = inner
        return r

    def all(self) -> list:
        return self._value if isinstance(self._value, list) else []


def _normalise(stmt) -> str:
    """Flatten a SQLAlchemy statement to single-spaced lowercase SQL.

    ``str(select(...))`` puts a newline before ``FROM``, so matching on a
    literal ``" from users"`` silently never fires. Collapsing whitespace
    first makes the table dispatch below actually work.
    """
    return " ".join(str(stmt).lower().split())


class _FakeSession:
    """Session that dispatches on the FROM table in the stringified SQL.

    Anchoring on ``" from <table>"`` avoids matching ``playlists.user_id``
    when looking for the users query (same trick as test_cleanup_lock.py).
    """

    def __init__(
        self,
        *,
        users: list,
        playlists: list,
        fail_on: str | None = None,
        rotation_offset: str | None = None,
    ) -> None:
        self._users = users
        self._playlists = playlists
        self._fail_on = fail_on
        self._rotation_offset = rotation_offset
        self.added: list = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, stmt):
        sql = _normalise(stmt)
        if self._fail_on is not None and f" from {self._fail_on}" in sql:
            raise RuntimeError("db exploded")
        if " from sync_logs" in sql:
            return _FakeResult(None)
        if " from app_settings" in sql:
            if self._rotation_offset is None:
                return _FakeResult(None)
            setting = MagicMock()
            setting.value = self._rotation_offset
            return _FakeResult(setting)
        if " from playlists" in sql:
            return _FakeResult(self._playlists)
        if " from users" in sql:
            return _FakeResult(self._users)
        return _FakeResult(None)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    def add(self, obj) -> None:
        # Stand in for the DB assigning a PK on flush/commit.
        if getattr(obj, "id", None) is None:
            obj.id = 42
        self.added.append(obj)


def _session_factory(
    *,
    users: list | None = None,
    playlists: list | None = None,
    fail_on: str | None = None,
    rotation_offset: str | None = None,
):
    def _make() -> _FakeSession:
        return _FakeSession(
            users=users or [],
            playlists=playlists or [],
            fail_on=fail_on,
            rotation_offset=rotation_offset,
        )

    return _make


def _make_user(user_id: int = 1) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    return user


def _make_playlist(playlist_id: int = 10, name: str = "Commute") -> MagicMock:
    playlist = MagicMock()
    playlist.id = playlist_id
    playlist.name = name
    playlist.spotify_playlist_id = f"sp-{playlist_id}"
    return playlist


class _NoopSpotify:
    """Spotify client that answers every playlist page as empty."""

    def __init__(self, *_a: object, **_kw: object) -> None:
        self.api_calls_used = 0

    def reset_api_counter(self) -> None:
        self.api_calls_used = 0

    async def __aenter__(self) -> _NoopSpotify:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_playlist_tracks(self, *_a: object, **_kw: object) -> dict:
        self.api_calls_used += 1
        return {"items": [], "next": None}


class _ExplodingLock:
    """Stands in for ``playlist_write_lock`` and blows up on acquisition.

    Exercises the outermost guard: anything escaping the per-user
    ``try`` must still reach the SyncLog finalisation.
    """

    def locked(self) -> bool:
        return False

    async def __aenter__(self):
        raise RuntimeError("write lock exploded")

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _restore_lock():
    original = locks.playlist_write_lock
    try:
        yield
    finally:
        locks.playlist_write_lock = original


# --------------------------------------------------------------------------
# update_all_playlists
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_playlist_update_finalises_log_when_user_read_fails():
    """The bare ``return`` on a failed user read used to orphan the row."""
    finalise = AsyncMock()

    with (
        patch("app.jobs.scheduler.async_session_maker", _session_factory(fail_on="users")),
        patch("app.jobs.scheduler._finalise_playlist_update_log", finalise),
    ):
        await scheduler.update_all_playlists()

    finalise.assert_awaited_once()
    _args, kwargs = finalise.await_args
    assert kwargs["status"] is SyncStatus.FAILED
    assert "db exploded" in kwargs["details"]


@pytest.mark.asyncio
async def test_playlist_update_finalises_log_on_unexpected_error():
    """Anything escaping the per-user try must still finalise the row."""
    finalise = AsyncMock()
    locks.playlist_write_lock = _ExplodingLock()

    with (
        patch("app.jobs.scheduler.async_session_maker", _session_factory(users=[(1,)])),
        patch("app.jobs.scheduler._finalise_playlist_update_log", finalise),
    ):
        await scheduler.update_all_playlists()

    finalise.assert_awaited_once()
    _args, kwargs = finalise.await_args
    assert kwargs["status"] is SyncStatus.FAILED
    assert "write lock exploded" in kwargs["details"]


@pytest.mark.asyncio
async def test_playlist_update_finalises_log_on_success():
    """The happy path still finalises — the refactor must not lose it."""
    finalise = AsyncMock()

    with (
        patch("app.jobs.scheduler.async_session_maker", _session_factory(users=[])),
        patch("app.jobs.scheduler._finalise_playlist_update_log", finalise),
    ):
        await scheduler.update_all_playlists()

    finalise.assert_awaited_once()
    _args, kwargs = finalise.await_args
    assert kwargs["status"] is SyncStatus.SUCCESS


@pytest.mark.asyncio
async def test_finalise_helper_is_a_noop_without_a_log_row():
    """If the RUNNING row was never created there is nothing to finalise."""
    factory = _session_factory()
    with patch("app.jobs.scheduler.async_session_maker", factory):
        await scheduler._finalise_playlist_update_log(
            None,
            status=SyncStatus.FAILED,
            details="ignored",
            failure_code="unknown",
        )
    # No exception, no session work — the guard clause returned early.


# --------------------------------------------------------------------------
# remove_played_episodes_from_playlists
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_finalises_log_when_get_token_raises_non_runtime_error():
    """The exact #174 case: only RuntimeError was caught around get_token.

    A ``TokenDecryptionError`` (or any httpx error out of the refresh
    path) escaped the job body and left the row RUNNING forever.
    """

    class _TokenDecryptionError(Exception):
        """Stand-in for the real decryption failure."""

    finalise = AsyncMock()

    class _Manager:
        def __init__(self, user_id: int) -> None:
            self._user_id = user_id

        async def get_token(self, *, min_remaining_seconds: int) -> str:
            raise _TokenDecryptionError("stored token is unreadable")

    with (
        patch(
            "app.jobs.scheduler.async_session_maker",
            _session_factory(users=[_make_user()], playlists=[_make_playlist()]),
        ),
        patch("app.jobs.scheduler.TokenManager", _Manager),
        patch("app.jobs.scheduler._finalise_cleanup_log", finalise),
    ):
        await scheduler.remove_played_episodes_from_playlists()

    finalise.assert_awaited_once()
    _args, kwargs = finalise.await_args
    assert kwargs["status"] is SyncStatus.FAILED
    assert "stored token is unreadable" in kwargs["details"]


@pytest.mark.asyncio
async def test_cleanup_still_skips_a_missing_user_without_failing_the_run():
    """``RuntimeError`` (user gone) stays a skip, not a run-level failure."""
    finalise = AsyncMock()

    class _Manager:
        def __init__(self, user_id: int) -> None:
            self._user_id = user_id

        async def get_token(self, *, min_remaining_seconds: int) -> str:
            raise RuntimeError(f"User {self._user_id} not found")

    with (
        patch(
            "app.jobs.scheduler.async_session_maker",
            _session_factory(users=[_make_user()], playlists=[_make_playlist()]),
        ),
        patch("app.jobs.scheduler.TokenManager", _Manager),
        patch("app.jobs.scheduler._finalise_cleanup_log", finalise),
    ):
        await scheduler.remove_played_episodes_from_playlists()

    finalise.assert_awaited_once()
    _args, kwargs = finalise.await_args
    assert kwargs["status"] is SyncStatus.SUCCESS


@pytest.mark.asyncio
async def test_cleanup_finalises_log_when_db_read_fails():
    """A failed users/playlists read must finalise, not bare-return."""
    finalise = AsyncMock()

    with (
        patch("app.jobs.scheduler.async_session_maker", _session_factory(fail_on="users")),
        patch("app.jobs.scheduler._finalise_cleanup_log", finalise),
    ):
        await scheduler.remove_played_episodes_from_playlists()

    finalise.assert_awaited_once()
    _args, kwargs = finalise.await_args
    assert kwargs["status"] is SyncStatus.FAILED
    assert "db exploded" in kwargs["details"]


@pytest.mark.asyncio
async def test_cleanup_finalises_log_on_unexpected_error():
    """Anything escaping the per-user try must still finalise the row."""
    finalise = AsyncMock()
    locks.playlist_write_lock = _ExplodingLock()

    with (
        patch(
            "app.jobs.scheduler.async_session_maker",
            _session_factory(users=[_make_user()], playlists=[_make_playlist()]),
        ),
        patch("app.jobs.scheduler._finalise_cleanup_log", finalise),
    ):
        await scheduler.remove_played_episodes_from_playlists()

    finalise.assert_awaited_once()
    _args, kwargs = finalise.await_args
    assert kwargs["status"] is SyncStatus.FAILED
    assert "write lock exploded" in kwargs["details"]


@pytest.mark.asyncio
async def test_cleanup_finalises_the_log_before_writing_the_rotation_cursor():
    """Ordering guarantee: close the row first, bookkeep second.

    Losing the rotation cursor costs one repeated pass; losing the
    finalisation strands the row forever. So the cursor write happens
    *after* ``_finalise_cleanup_log`` and can never displace it (#174).
    We prove it by making the cursor write explode and observing that the
    row was already closed.
    """
    finalise = AsyncMock()
    persist = AsyncMock(side_effect=RuntimeError("settings table is gone"))

    class _Manager:
        def __init__(self, user_id: int) -> None:
            self._user_id = user_id

        async def get_token(self, *, min_remaining_seconds: int) -> str:
            return "token"

    with (
        patch(
            "app.jobs.scheduler.async_session_maker",
            # A stored cursor of 1 plus a run that reaches every playlist
            # means the cursor resets to 0 — i.e. an actual write.
            _session_factory(
                users=[_make_user()],
                playlists=[_make_playlist(), _make_playlist(11, "Gym")],
                rotation_offset="1",
            ),
        ),
        patch("app.jobs.scheduler.TokenManager", _Manager),
        patch("app.jobs.scheduler.SpotifyService", _NoopSpotify),
        patch("app.jobs.scheduler._persist_cleanup_rotation_offset", persist),
        patch("app.jobs.scheduler._finalise_cleanup_log", finalise),
        pytest.raises(RuntimeError, match="settings table is gone"),
    ):
        await scheduler.remove_played_episodes_from_playlists()

    finalise.assert_awaited_once()
    _args, kwargs = finalise.await_args
    assert kwargs["status"] is SyncStatus.SUCCESS
    persist.assert_awaited_once_with(0)


@pytest.mark.asyncio
async def test_persist_rotation_offset_swallows_write_failures():
    """The helper itself must not raise — the caller has a row to close."""

    def _exploding_factory():
        raise RuntimeError("no sessions today")

    with patch("app.jobs.scheduler.async_session_maker", _exploding_factory):
        await scheduler._persist_cleanup_rotation_offset(3)
    # No exception escaped.


@pytest.mark.asyncio
async def test_finalise_cleanup_helper_is_a_noop_without_a_log_row():
    """Mirror of the playlist-update guard clause."""
    with patch("app.jobs.scheduler.async_session_maker", _session_factory()):
        await scheduler._finalise_cleanup_log(
            None,
            status=SyncStatus.FAILED,
            details="ignored",
            failure_code="unknown",
            playlists_attempted=0,
            playlists_failed=0,
            api_calls_used=0,
        )


@pytest.mark.asyncio
async def test_finalise_cleanup_helper_writes_the_outcome():
    """The helper stamps status, completion time and counters on the row."""
    row = MagicMock()
    row.id = 42

    class _RowSession(_FakeSession):
        async def execute(self, stmt):
            if " from sync_logs" in _normalise(stmt):
                return _FakeResult(row)
            return await super().execute(stmt)

    def _factory() -> _RowSession:
        return _RowSession(users=[], playlists=[])

    before = datetime.now(UTC)
    with patch("app.jobs.scheduler.async_session_maker", _factory):
        await scheduler._finalise_cleanup_log(
            42,
            status=SyncStatus.FAILED,
            details="something broke",
            failure_code="unknown",
            playlists_attempted=3,
            playlists_failed=1,
            api_calls_used=17,
        )

    assert row.status is SyncStatus.FAILED
    assert row.details == "something broke"
    assert row.failure_code == "unknown"
    assert row.playlists_attempted == 3
    assert row.playlists_failed == 1
    assert row.api_calls_used == 17
    assert row.completed_at >= before
