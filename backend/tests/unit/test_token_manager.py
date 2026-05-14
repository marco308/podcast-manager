"""Unit tests for :class:`app.services.token_manager.TokenManager`.

Issue #89: covers the three invariants we care about.

  1. ``get_token`` refreshes only when fewer than ``min_remaining_seconds``
     are left on the cached token.
  2. Two concurrent ``get_token`` calls produce a single refresh — the
     per-user ``asyncio.Lock`` must serialise them and the second caller
     must observe the freshly-persisted token rather than firing its own
     refresh (Spotify rotates refresh tokens, so two parallel refreshes
     can invalidate each other).
  3. ``force_refresh`` refreshes unconditionally — used as the on-401
     callback where the cached expiry has lied to us.

TODO(issue #89, PR1): these tests require ``pytest-asyncio`` and a way
to monkey-patch ``async_session_maker``. Neither is in
``requirements.txt`` today (this PR deliberately does not add new
top-level deps — that's scope creep). Install ``pytest-asyncio`` and
``respx`` locally to run.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.token_manager import TokenManager


def _make_user(*, user_id: int = 1, expires_in: int = 3600) -> MagicMock:
    """Build a stand-in for a :class:`User` row.

    Tokens stored on the row are pre-encoded as ``enc:<plain>`` — paired
    with the ``_make_encryption`` fake below this keeps the round-trip
    simple to reason about in assertions.
    """
    user = MagicMock()
    user.id = user_id
    user.access_token = "enc:cached-access"
    user.refresh_token = "enc:cached-refresh"
    user.token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    return user


def _make_encryption() -> MagicMock:
    enc = MagicMock()
    enc.decrypt.side_effect = lambda c: c.removeprefix("enc:")
    enc.encrypt.side_effect = lambda p: f"enc:{p}"
    return enc


class _FakeSession:
    """Minimal async-context-manager DB session that returns a fixed user."""

    def __init__(self, user: MagicMock) -> None:
        self._user = user
        self.commits = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, _stmt):  # noqa: D401
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._user
        return result

    async def commit(self) -> None:
        self.commits += 1


def _session_factory(user: MagicMock):
    """Return a callable that produces ``_FakeSession`` instances."""
    sessions: list[_FakeSession] = []

    def _make() -> _FakeSession:
        sess = _FakeSession(user)
        sessions.append(sess)
        return sess

    _make.sessions = sessions  # type: ignore[attr-defined]
    return _make


@pytest.fixture(autouse=True)
def _clear_locks():
    """Reset the class-level lock registry between tests."""
    TokenManager._user_locks.clear()
    yield
    TokenManager._user_locks.clear()


@pytest.mark.asyncio
async def test_get_token_returns_cached_when_fresh():
    """Token with > min_remaining_seconds of life left should not trigger a refresh."""
    user = _make_user(expires_in=3600)  # 1 hour remaining
    factory = _session_factory(user)
    refresh_mock = AsyncMock()

    with (
        patch("app.services.token_manager.async_session_maker", factory),
        patch("app.services.token_manager.get_encryption_service", return_value=_make_encryption()),
        patch("app.services.token_manager.SpotifyService.refresh_access_token", refresh_mock),
    ):
        tm = TokenManager(user_id=user.id)
        token = await tm.get_token(min_remaining_seconds=300)

    assert token == "cached-access"
    refresh_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_token_refreshes_when_under_threshold():
    """A token with less than min_remaining_seconds left should be refreshed."""
    user = _make_user(expires_in=60)  # 1 minute remaining < 5 minute threshold
    factory = _session_factory(user)
    refresh_mock = AsyncMock(
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        }
    )

    with (
        patch("app.services.token_manager.async_session_maker", factory),
        patch("app.services.token_manager.get_encryption_service", return_value=_make_encryption()),
        patch("app.services.token_manager.SpotifyService.refresh_access_token", refresh_mock),
    ):
        tm = TokenManager(user_id=user.id)
        token = await tm.get_token(min_remaining_seconds=300)

    assert token == "new-access"
    refresh_mock.assert_awaited_once_with("cached-refresh")
    # The new token should have been persisted to the user row.
    assert user.access_token == "enc:new-access"
    assert user.refresh_token == "enc:new-refresh"


@pytest.mark.asyncio
async def test_concurrent_get_token_shares_single_refresh():
    """Two callers racing get_token must produce exactly one Spotify refresh.

    This is the key correctness property: Spotify rotates the refresh
    token on every successful POST /api/token, so two concurrent
    refreshes can invalidate each other and brick the user.
    """
    user = _make_user(expires_in=60)
    factory = _session_factory(user)

    refresh_calls = 0
    new_expiry = datetime.now(UTC) + timedelta(hours=1)

    async def _slow_refresh(_refresh_token: str) -> dict:
        nonlocal refresh_calls
        refresh_calls += 1
        # Yield so the second caller has a chance to enter the slow path
        # before we mutate `user.token_expires_at` further down.
        await asyncio.sleep(0.05)
        # Simulate the side-effect the real call would have on the user row.
        user.token_expires_at = new_expiry
        user.access_token = "enc:new-access"
        user.refresh_token = "enc:new-refresh"
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_at": new_expiry,
        }

    with (
        patch("app.services.token_manager.async_session_maker", factory),
        patch("app.services.token_manager.get_encryption_service", return_value=_make_encryption()),
        patch("app.services.token_manager.SpotifyService.refresh_access_token", side_effect=_slow_refresh),
    ):
        tm = TokenManager(user_id=user.id)
        results = await asyncio.gather(
            tm.get_token(min_remaining_seconds=300),
            tm.get_token(min_remaining_seconds=300),
        )

    assert refresh_calls == 1, "concurrent get_token must collapse into a single refresh"
    assert results == ["new-access", "new-access"]


@pytest.mark.asyncio
async def test_force_refresh_always_refreshes():
    """force_refresh bypasses the freshness check — used on 401 recovery."""
    user = _make_user(expires_in=3600)  # Plenty of life left
    factory = _session_factory(user)
    refresh_mock = AsyncMock(
        return_value={
            "access_token": "rotated-access",
            "refresh_token": "rotated-refresh",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        }
    )

    with (
        patch("app.services.token_manager.async_session_maker", factory),
        patch("app.services.token_manager.get_encryption_service", return_value=_make_encryption()),
        patch("app.services.token_manager.SpotifyService.refresh_access_token", refresh_mock),
    ):
        tm = TokenManager(user_id=user.id)
        token = await tm.force_refresh()

    assert token == "rotated-access"
    refresh_mock.assert_awaited_once()
