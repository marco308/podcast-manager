"""Unit tests for the cleanup job's API budget and rotation cursor.

Issue #182. Two related defects:

  - the per-run ``CLEANUP_API_CALL_BUDGET`` was only checked *between*
    playlists, so a single deep playlist could page well past the
    allowance before anything noticed;
  - the "next run picks up where we left off" comment was false. There
    was no cursor, so every run restarted at the head of the list and
    playlists past the budget cut-off were never cleaned at all.

The fix checks the budget inside the pagination loop (deferring the
whole playlist rather than half-cleaning it) and persists a rotation
cursor in ``app_settings`` so the next run starts on the first playlist
the previous one didn't reach.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jobs import scheduler


def _normalise(stmt) -> str:
    """Flatten a statement to single-spaced lowercase SQL (see #174 tests)."""
    return " ".join(str(stmt).lower().split())


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


class _FakeSession:
    def __init__(self, *, users: list, playlists: list, rotation_offset: str | None) -> None:
        self._users = users
        self._playlists = playlists
        self._rotation_offset = rotation_offset

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, stmt):
        sql = _normalise(stmt)
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
        if getattr(obj, "id", None) is None:
            obj.id = 99


def _session_factory(*, playlist_count: int, rotation_offset: str | None = None):
    user = MagicMock()
    user.id = 1

    playlists = []
    for i in range(playlist_count):
        p = MagicMock()
        p.id = i
        p.name = f"pl{i}"
        p.spotify_playlist_id = f"sp{i}"
        playlists.append(p)

    def _make() -> _FakeSession:
        return _FakeSession(users=[user], playlists=playlists, rotation_offset=rotation_offset)

    return _make


class _RecordingSpotify:
    """Fake client: one API call per page, records what it was asked for.

    ``pages`` controls how many pages each playlist reports before
    ``next`` goes null, which is how a single playlist can be made deep
    enough to exhaust the budget mid-pagination.
    """

    instances: list[_RecordingSpotify] = []

    def __init__(self, *_a: object, pages: int = 1, **_kw: object) -> None:
        self.api_calls_used = 0
        self.visited: list[str] = []
        self.removed: list[list[str]] = []
        self._pages = pages
        self._page_counts: dict[str, int] = {}
        _RecordingSpotify.instances.append(self)

    def reset_api_counter(self) -> None:
        self.api_calls_used = 0

    async def __aenter__(self) -> _RecordingSpotify:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_playlist_tracks(self, playlist_id: str, limit: int = 50, offset: int = 0, **_kw: object) -> dict:
        self.api_calls_used += 1
        self.visited.append(playlist_id)
        seen = self._page_counts.get(playlist_id, 0) + 1
        self._page_counts[playlist_id] = seen
        return {
            "items": [
                {"track": {"uri": f"spotify:episode:{playlist_id}-{seen}", "resume_point": {"fully_played": True}}}
            ],
            "next": "more" if seen < self._pages else None,
        }

    async def remove_tracks_from_playlist(self, _playlist_id: str, uris: list[str], **_kw: object) -> None:
        self.api_calls_used += 1
        self.removed.append(list(uris))


class _Manager:
    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    async def get_token(self, *, min_remaining_seconds: int) -> str:
        return "token"

    async def force_refresh(self) -> str:
        return "token"


@pytest.fixture(autouse=True)
def _reset_instances():
    _RecordingSpotify.instances.clear()
    yield
    _RecordingSpotify.instances.clear()


def _spotify_factory(pages: int = 1):
    def _ctor(*a: object, **kw: object) -> _RecordingSpotify:
        return _RecordingSpotify(*a, pages=pages, **kw)

    return _ctor


async def _run(*, playlist_count: int, budget: int, rotation_offset: str | None = None, pages: int = 1):
    """Drive one cleanup run and return (finalise_kwargs, persist_mock, client)."""
    finalise = AsyncMock()
    persist = AsyncMock()

    with (
        patch(
            "app.jobs.scheduler.async_session_maker",
            _session_factory(playlist_count=playlist_count, rotation_offset=rotation_offset),
        ),
        patch("app.jobs.scheduler.TokenManager", _Manager),
        patch("app.jobs.scheduler.SpotifyService", _spotify_factory(pages)),
        patch("app.jobs.scheduler.CLEANUP_API_CALL_BUDGET", budget),
        patch("app.jobs.scheduler._persist_cleanup_rotation_offset", persist),
        patch("app.jobs.scheduler._finalise_cleanup_log", finalise),
    ):
        await scheduler.remove_played_episodes_from_playlists()

    _args, kwargs = finalise.await_args
    return kwargs, persist, _RecordingSpotify.instances[0]


# --------------------------------------------------------------------------
# Rotation cursor
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_limited_run_advances_the_cursor_to_the_first_missed_playlist():
    """5 playlists, a budget that covers 2 ⇒ next run must start at index 2."""
    # Each playlist costs 2 calls (one page + one removal), so a budget of
    # 4 lets exactly two playlists through.
    kwargs, persist, client = await _run(playlist_count=5, budget=4)

    assert client.visited == ["sp0", "sp1"]
    assert kwargs["playlists_attempted"] == 2
    persist.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_stored_cursor_rotates_the_processing_order():
    """A stored cursor of 2 must put playlist 2 at the head of the run."""
    _kwargs, _persist, client = await _run(playlist_count=5, budget=1000, rotation_offset="2")

    assert client.visited == ["sp2", "sp3", "sp4", "sp0", "sp1"], (
        "the run must start on the playlist the previous one stopped at"
    )


@pytest.mark.asyncio
async def test_cursor_walks_the_whole_list_across_consecutive_runs():
    """Two budget-limited runs in sequence must cover disjoint playlists.

    This is the starvation property: without the cursor, run 2 would
    re-clean sp0/sp1 and sp2..sp4 would never be touched.
    """
    _k1, persist1, client1 = await _run(playlist_count=5, budget=4)
    assert client1.visited == ["sp0", "sp1"]
    next_offset = persist1.await_args.args[0]

    _RecordingSpotify.instances.clear()
    _k2, persist2, client2 = await _run(playlist_count=5, budget=4, rotation_offset=str(next_offset))

    assert client2.visited == ["sp2", "sp3"]
    assert persist2.await_args.args[0] == 4


@pytest.mark.asyncio
async def test_complete_run_resets_the_cursor():
    """Reaching every playlist must clear a previously stored cursor."""
    kwargs, persist, client = await _run(playlist_count=3, budget=1000, rotation_offset="2")

    assert len(client.visited) == 3
    assert kwargs["playlists_attempted"] == 3
    persist.assert_awaited_once_with(0)


@pytest.mark.asyncio
async def test_complete_run_from_a_zero_cursor_writes_nothing():
    """No cursor movement ⇒ no pointless app_settings write every 30 minutes."""
    _kwargs, persist, _client = await _run(playlist_count=3, budget=1000)

    persist.assert_not_awaited()


# --------------------------------------------------------------------------
# Budget enforcement inside a single playlist
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_is_enforced_inside_the_pagination_loop():
    """A deep playlist must stop paging once the budget is spent.

    Previously the check only ran between playlists, so one playlist
    could page indefinitely past the allowance.
    """
    kwargs, _persist, client = await _run(playlist_count=1, budget=3, pages=50)

    assert len(client.visited) == 3, "paging must stop at the budget, not at the end of the playlist"


@pytest.mark.asyncio
async def test_playlist_deferred_mid_pagination_is_not_half_cleaned():
    """A playlist cut off mid-paging must not have deletions applied.

    Its played-episode list is incomplete, so removing from it would be
    a partial clean based on a partial read. It is deferred whole and
    doesn't count as attempted (issue #161).
    """
    kwargs, persist, client = await _run(playlist_count=1, budget=3, pages=50)

    assert client.removed == [], "a deferred playlist must not be partially cleaned"
    assert kwargs["playlists_attempted"] == 0, "a deferred playlist was not attempted"
    # Only one playlist exists, so there is nowhere to rotate to.
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_playlist_too_deep_for_one_budget_does_not_pin_the_cursor():
    """The head playlist can never finish — the tail must still get a turn.

    ``playlists_attempted`` excludes a mid-pagination deferral (#161), so
    driving the cursor from it would leave the offset at 0 forever and
    the other four playlists would never be cleaned. The cursor is driven
    by playlists *consumed*, which includes the deferred one.
    """
    kwargs, persist, client = await _run(playlist_count=5, budget=3, pages=50)

    assert client.visited == ["sp0", "sp0", "sp0"], "the budget went entirely on the deep playlist"
    assert kwargs["playlists_attempted"] == 0
    # The next run must move on to sp1 rather than restart on sp0.
    persist.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_shallow_playlists_are_cleaned_normally():
    """Sanity check on the fake: within budget, everything is removed."""
    kwargs, _persist, client = await _run(playlist_count=2, budget=1000)

    assert client.visited == ["sp0", "sp1"]
    assert client.removed == [["spotify:episode:sp0-1"], ["spotify:episode:sp1-1"]]
    assert kwargs["playlists_attempted"] == 2
