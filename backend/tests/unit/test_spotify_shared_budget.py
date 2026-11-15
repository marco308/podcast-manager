"""Issue #314: one Spotify rate window per process, and a shorter 429 wait in requests."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.routers import _deps
from app.services.playlist_builder import PlaylistBuilder
from app.services.spotify import (
    MAX_RETRY_AFTER_SECONDS,
    RATE_LIMIT_THRESHOLD,
    REQUEST_MAX_RETRY_AFTER_SECONDS,
    SpotifyService,
)


def _transport(respond):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return respond(len(calls), request)

    return httpx.MockTransport(handler), calls


class TestSharedWindow:
    @pytest.mark.asyncio
    async def test_one_instances_traffic_throttles_another(self):
        """A job and a manual sync pace against the same window."""
        job = SpotifyService(access_token="job")
        manual = SpotifyService(access_token="manual")
        now = time.monotonic()
        for _ in range(RATE_LIMIT_THRESHOLD):
            job._request_timestamps.append(now)

        with patch("app.services.spotify.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            await manual._throttle_if_needed()

        sleep_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_requests_from_any_instance_fill_the_window(self):
        transport, _ = _transport(lambda n, request: httpx.Response(200, json={}))
        async with httpx.AsyncClient(transport=transport) as client:
            first = SpotifyService(access_token="a", client=client)
            second = SpotifyService(access_token="b", client=client)
            await first._request_with_retry(client, "GET", "https://api.spotify.com/v1/me")
            await second._request_with_retry(client, "GET", "https://api.spotify.com/v1/me")

        assert len(first._request_timestamps) == 2
        # The per-run call counter stays per instance.
        assert first.api_calls_used == 1
        assert second.api_calls_used == 1


class TestRequestCap:
    def test_request_cap_is_shorter_than_the_job_cap(self):
        assert REQUEST_MAX_RETRY_AFTER_SECONDS < MAX_RETRY_AFTER_SECONDS

    @pytest.mark.asyncio
    async def test_wait_over_the_request_cap_fails_fast(self):
        transport, calls = _transport(
            lambda n, request: httpx.Response(
                429, headers={"Retry-After": str(REQUEST_MAX_RETRY_AFTER_SECONDS + 1)}, json={}
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            service = SpotifyService(access_token="t", client=client, max_retry_after=REQUEST_MAX_RETRY_AFTER_SECONDS)
            with (
                patch("app.services.spotify.asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
                pytest.raises(httpx.HTTPStatusError) as exc_info,
            ):
                await service._request_with_retry(client, "GET", "https://api.spotify.com/v1/me")

        assert exc_info.value.response.status_code == 429
        assert calls == ["GET"]
        sleep_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wait_within_the_request_cap_is_still_retried(self):
        def respond(n, request):
            if n == 1:
                return httpx.Response(429, headers={"Retry-After": str(REQUEST_MAX_RETRY_AFTER_SECONDS)}, json={})
            return httpx.Response(200, json={})

        transport, calls = _transport(respond)
        async with httpx.AsyncClient(transport=transport) as client:
            service = SpotifyService(access_token="t", client=client, max_retry_after=REQUEST_MAX_RETRY_AFTER_SECONDS)
            with patch("app.services.spotify.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
                await service._request_with_retry(client, "GET", "https://api.spotify.com/v1/me")

        assert calls == ["GET", "GET"]
        sleep_mock.assert_awaited_once_with(REQUEST_MAX_RETRY_AFTER_SECONDS)

    @pytest.mark.asyncio
    async def test_a_job_still_sleeps_through_the_same_wait(self):
        """The default (job) cap is untouched: 11s is slept, not refused."""

        def respond(n, request):
            if n == 1:
                return httpx.Response(429, headers={"Retry-After": str(REQUEST_MAX_RETRY_AFTER_SECONDS + 1)}, json={})
            return httpx.Response(200, json={})

        transport, calls = _transport(respond)
        async with httpx.AsyncClient(transport=transport) as client:
            service = SpotifyService(access_token="t", client=client)
            with patch("app.services.spotify.asyncio.sleep", new_callable=AsyncMock):
                await service._request_with_retry(client, "GET", "https://api.spotify.com/v1/me")

        assert calls == ["GET", "GET"]

    @pytest.mark.asyncio
    async def test_route_clients_use_the_request_cap(self, monkeypatch):
        manager = MagicMock()
        manager.get_token = AsyncMock(return_value="token")
        monkeypatch.setattr(_deps, "TokenManager", MagicMock(return_value=manager))

        spotify, _ = await _deps.spotify_client(AsyncMock(), 1)

        assert spotify._max_retry_after == REQUEST_MAX_RETRY_AFTER_SECONDS

    @pytest.mark.asyncio
    async def test_builder_passes_its_cap_to_its_client(self):
        manager = MagicMock()
        manager.get_token = AsyncMock(return_value="token")
        user = MagicMock(id=1)

        manual = PlaylistBuilder(
            AsyncMock(), user, token_manager=manager, max_retry_after=REQUEST_MAX_RETRY_AFTER_SECONDS
        )
        scheduled = PlaylistBuilder(AsyncMock(), user, token_manager=manager)

        assert (await manual._get_spotify_client())._max_retry_after == REQUEST_MAX_RETRY_AFTER_SECONDS
        assert (await scheduled._get_spotify_client())._max_retry_after == MAX_RETRY_AFTER_SECONDS
