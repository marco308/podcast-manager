"""Unit tests for :class:`SpotifyService`'s rate-limit budget plumbing.

Issue #89, PR2. Covers:

  1. Sliding-window deque math — at threshold the next call sleeps, and
     timestamps that fall out of the 30s window stop counting.
  2. ``cleanup_mode=True`` + ``Retry-After: 120`` raises
     :class:`CleanupBudgetExceeded` instead of sleeping for two minutes.
  3. ``cleanup_mode=False`` keeps the existing sleep-and-retry contract.
  4. ``api_calls_used`` increments on every request (including retries).

Uses ``httpx.MockTransport`` per the PR1 convention — no ``respx``.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.spotify import (
    RATE_LIMIT_THRESHOLD,
    RATE_LIMIT_WINDOW_SECONDS,
    CleanupBudgetExceeded,
    SpotifyService,
)


@pytest.mark.asyncio
async def test_throttle_sleeps_when_window_full():
    """At the threshold, the next call must call asyncio.sleep."""
    service = SpotifyService(access_token="t")
    now = time.monotonic()
    # Pack the deque with threshold timestamps all inside the 30s window.
    for i in range(RATE_LIMIT_THRESHOLD):
        service._request_timestamps.append(now - (i * 0.01))

    with patch("app.services.spotify.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        await service._throttle_if_needed()
        sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_throttle_does_not_sleep_when_window_stale():
    """Timestamps older than 30s must be evicted and not trigger a sleep."""
    service = SpotifyService(access_token="t")
    # All entries pre-date the window — they should be popped on the first call.
    stale = time.monotonic() - (RATE_LIMIT_WINDOW_SECONDS + 5)
    for _ in range(RATE_LIMIT_THRESHOLD):
        service._request_timestamps.append(stale)

    with patch("app.services.spotify.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        await service._throttle_if_needed()
        sleep_mock.assert_not_awaited()
    assert len(service._request_timestamps) == 0


@pytest.mark.asyncio
async def test_throttle_does_not_sleep_below_threshold():
    """Below the threshold, no sleep regardless of window."""
    service = SpotifyService(access_token="t")
    now = time.monotonic()
    for _ in range(RATE_LIMIT_THRESHOLD - 1):
        service._request_timestamps.append(now)

    with patch("app.services.spotify.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        await service._throttle_if_needed()
        sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_mode_aborts_on_long_retry_after():
    """cleanup_mode=True must raise CleanupBudgetExceeded for Retry-After > 60s."""
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "120"}, json={})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = SpotifyService(access_token="t", client=client)
        with pytest.raises(CleanupBudgetExceeded):
            await service._request_with_retry(
                client,
                "GET",
                "https://api.spotify.com/v1/playlists/p1/items",
                cleanup_mode=True,
            )


@pytest.mark.asyncio
async def test_cleanup_mode_does_not_abort_on_short_retry_after():
    """Retry-After at or under the cleanup limit must still sleep-and-retry."""
    call_count = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "30"}, json={})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = SpotifyService(access_token="t", client=client)
        with patch("app.services.spotify.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            resp = await service._request_with_retry(
                client,
                "GET",
                "https://api.spotify.com/v1/playlists/p1/items",
                cleanup_mode=True,
            )
        assert resp.status_code == 200
        sleep_mock.assert_awaited()  # the 30s wait got slept through


@pytest.mark.asyncio
async def test_non_cleanup_mode_sleeps_on_long_retry_after():
    """cleanup_mode=False keeps the original sleep-and-retry behaviour."""
    call_count = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "120"}, json={})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = SpotifyService(access_token="t", client=client)
        with patch("app.services.spotify.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            resp = await service._request_with_retry(
                client,
                "GET",
                "https://api.spotify.com/v1/playlists/p1/items",
                # cleanup_mode defaults to False
            )
        assert resp.status_code == 200
        # Should have slept for the Retry-After window, not raised.
        sleep_mock.assert_awaited()


@pytest.mark.asyncio
async def test_api_calls_used_increments_on_each_request():
    """Counter must increment on every issued request, including retries."""
    call_count = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = SpotifyService(access_token="t", client=client)
        assert service.api_calls_used == 0

        with patch("app.services.spotify.asyncio.sleep", new=AsyncMock()):
            await service._request_with_retry(
                client,
                "GET",
                "https://api.spotify.com/v1/test",
            )

        # 1 initial 429 + 1 retry = 2 requests.
        assert service.api_calls_used == 2


@pytest.mark.asyncio
async def test_reset_api_counter_zeroes_counter_but_keeps_window():
    """reset_api_counter() must clear api_calls_used but leave the deque alone."""
    service = SpotifyService(access_token="t")
    service.api_calls_used = 42
    service._request_timestamps.append(time.monotonic())

    service.reset_api_counter()

    assert service.api_calls_used == 0
    # Window state should persist across runs — Spotify doesn't reset because we did.
    assert len(service._request_timestamps) == 1
