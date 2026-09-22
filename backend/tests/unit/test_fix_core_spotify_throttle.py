"""Unit tests for two SpotifyService robustness fixes from issue #182.

1. The soft throttle claimed to hold a 150-requests-per-30s window but
   slept a flat 0.1s and carried on — a burst sailed straight past the
   threshold. It now sleeps until the oldest surplus timestamp has aged
   out, so the request about to be issued has a genuine slot.

2. ``int(response.headers["Retry-After"])`` crashed on the spec-legal
   HTTP-date form of the header, turning a rate-limit response into an
   unhandled ``ValueError``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import spotify as spotify_module
from app.services.spotify import (
    RATE_LIMIT_THRESHOLD,
    RATE_LIMIT_WINDOW_SECONDS,
    SOFT_THROTTLE_SLEEP_SECONDS,
    SpotifyService,
)


class _FakeClock:
    """Controllable monotonic clock whose ``sleep`` advances it."""

    def __init__(self, now: float = 10_000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.now += duration


def _fill_window(service: SpotifyService, clock: _FakeClock, *, oldest_age: float) -> None:
    """Pack the deque with exactly RATE_LIMIT_THRESHOLD in-window entries.

    Entries are appended oldest-first, matching production order, with
    the oldest ``oldest_age`` seconds in the past.
    """
    span = 1.0
    step = span / RATE_LIMIT_THRESHOLD
    start = clock.now - oldest_age
    for i in range(RATE_LIMIT_THRESHOLD):
        service._request_timestamps.append(start + i * step)


@pytest.mark.asyncio
async def test_throttle_sleep_actually_frees_a_slot():
    """After the computed sleep, the window must have room for one request.

    The regression this pins: with a flat 0.1s nap (or a wait that is one
    entry short) the very next call still finds a full window, so the
    throttle never actually holds the stated rate.
    """
    clock = _FakeClock()
    service = SpotifyService(access_token="t")
    # Oldest entry is 29s old — 1s short of ageing out of the 30s window.
    _fill_window(service, clock, oldest_age=RATE_LIMIT_WINDOW_SECONDS - 1)

    with (
        patch("app.services.spotify.time.monotonic", clock.monotonic),
        patch("app.services.spotify.asyncio.sleep", clock.sleep),
    ):
        await service._throttle_if_needed()
        assert clock.sleeps, "a full window must throttle"

        # Second call: the wait above should have aged the oldest entry
        # out, so this one finds room and does not sleep again.
        sleeps_before = len(clock.sleeps)
        await service._throttle_if_needed()

    assert len(clock.sleeps) == sleeps_before, "the first wait did not actually free a slot"
    assert len(service._request_timestamps) < RATE_LIMIT_THRESHOLD


@pytest.mark.asyncio
async def test_throttle_wait_is_derived_from_the_window_not_a_flat_nap():
    """The sleep must be the real time-to-free, not SOFT_THROTTLE_SLEEP_SECONDS."""
    clock = _FakeClock()
    service = SpotifyService(access_token="t")
    _fill_window(service, clock, oldest_age=RATE_LIMIT_WINDOW_SECONDS - 5)

    with (
        patch("app.services.spotify.time.monotonic", clock.monotonic),
        patch("app.services.spotify.asyncio.sleep", clock.sleep),
    ):
        await service._throttle_if_needed()

    assert clock.sleeps == [pytest.approx(5.0, abs=0.01)], f"expected a ~5s window-derived wait, got {clock.sleeps}"


@pytest.mark.asyncio
async def test_throttle_floor_applies_when_the_window_is_about_to_drain():
    """A near-zero computed wait still yields to the event loop."""
    clock = _FakeClock()
    service = SpotifyService(access_token="t")
    # Oldest entry is a hair inside the window — computed wait ≈ 0.
    _fill_window(service, clock, oldest_age=RATE_LIMIT_WINDOW_SECONDS - 0.001)

    with (
        patch("app.services.spotify.time.monotonic", clock.monotonic),
        patch("app.services.spotify.asyncio.sleep", clock.sleep),
    ):
        await service._throttle_if_needed()

    assert clock.sleeps == [SOFT_THROTTLE_SLEEP_SECONDS]


@pytest.mark.asyncio
async def test_throttle_is_a_noop_below_the_threshold():
    """Under the threshold there is nothing to pace."""
    clock = _FakeClock()
    service = SpotifyService(access_token="t")
    _fill_window(service, clock, oldest_age=RATE_LIMIT_WINDOW_SECONDS - 1)
    service._request_timestamps.popleft()

    with (
        patch("app.services.spotify.time.monotonic", clock.monotonic),
        patch("app.services.spotify.asyncio.sleep", clock.sleep),
    ):
        await service._throttle_if_needed()

    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_http_date_retry_after_does_not_crash():
    """Spotify may legally send an HTTP-date; we fall back to 5s."""
    calls = 0

    def _handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
                json={},
            )
        return httpx.Response(200, json={"ok": True})

    sleep_mock = AsyncMock()
    transport = httpx.MockTransport(_handler)

    with patch("app.services.spotify.asyncio.sleep", sleep_mock):
        async with httpx.AsyncClient(transport=transport) as client:
            service = SpotifyService(access_token="t")
            response = await service._request_with_retry(client, "GET", "https://example.test/x")

    assert response.status_code == 200
    sleep_mock.assert_awaited_once_with(5)


@pytest.mark.asyncio
async def test_http_date_retry_after_does_not_trip_the_cleanup_abort():
    """The 5s fallback is under the cleanup limit, so cleanup keeps going.

    An unparseable header must not be treated as a multi-minute wait and
    abort the run.
    """
    calls = 0

    def _handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "not-a-number"}, json={})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(_handler)

    with patch("app.services.spotify.asyncio.sleep", AsyncMock()):
        async with httpx.AsyncClient(transport=transport) as client:
            service = SpotifyService(access_token="t")
            response = await service._request_with_retry(client, "GET", "https://example.test/x", cleanup_mode=True)

    assert response.status_code == 200
    assert spotify_module.CLEANUP_MODE_RETRY_AFTER_LIMIT > 5
