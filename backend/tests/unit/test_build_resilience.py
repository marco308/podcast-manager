"""Resilience fixes for playlist builds against a flaky or throttling Spotify.

1. ``replace_playlist_items`` is a PUT then POST appends; a failed append left
   the playlist truncated until the next run. A failure after the PUT now
   retries the whole replace once.
2. A ``Retry-After`` above the 5-minute cap used to sleep the cap and retry
   into another 429 — with ``playlist_write_lock`` held. It now fails fast.
3. ``_classify_failure`` matched "401"/"429" anywhere in the error text, so a
   playlist called "Top 401" was reported as an expired token. It now reads
   only exception types and HTTP status codes.
4. The daily update used APScheduler's 1s misfire grace, so a brief stall at
   the scheduled moment dropped the day's run.
5. The builder opened a new HTTP connection for every Spotify request.

The empty-tail-page fix for the oldest-first walk is in test_fetch_walks.py.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.jobs import scheduler
from app.services.playlist_builder import EpisodeFetchError, PlaylistBuilder
from app.services.spotify import MAX_RETRY_AFTER_SECONDS, SpotifyService

ITEMS_URL = "https://api.spotify.com/v1/playlists/p1/items"


def _uris(n: int) -> list[str]:
    return [f"spotify:episode:e{i}" for i in range(n)]


def _recording_transport(respond):
    """MockTransport that records ``(method, uri count)`` for every request."""
    calls: list[tuple[str, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append((request.method, len(body.get("uris", []))))
        return respond(len(calls), request)

    return httpx.MockTransport(handler), calls


class TestReplaceRetriesATruncatingFailure:
    @pytest.mark.asyncio
    async def test_failed_append_retries_the_whole_replace(self):
        def respond(n, request):
            # Third request is the second POST of the first attempt.
            return httpx.Response(500 if n == 3 else 201, json={})

        transport, calls = _recording_transport(respond)
        async with httpx.AsyncClient(transport=transport) as client:
            await SpotifyService(access_token="t", client=client).replace_playlist_items("p1", _uris(250))

        assert calls == [
            ("PUT", 100),
            ("POST", 100),
            ("POST", 50),
            ("PUT", 100),
            ("POST", 100),
            ("POST", 50),
        ]

    @pytest.mark.asyncio
    async def test_retries_only_once(self):
        def respond(n, request):
            return httpx.Response(500 if request.method == "POST" else 201, json={})

        transport, calls = _recording_transport(respond)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await SpotifyService(access_token="t", client=client).replace_playlist_items("p1", _uris(150))

        assert calls == [("PUT", 100), ("POST", 50), ("PUT", 100), ("POST", 50)]

    @pytest.mark.asyncio
    async def test_failed_put_is_not_retried(self):
        """The PUT failing leaves the playlist as it was — nothing to repair."""
        transport, calls = _recording_transport(lambda n, request: httpx.Response(500, json={}))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await SpotifyService(access_token="t", client=client).replace_playlist_items("p1", _uris(150))

        assert calls == [("PUT", 100)]

    @pytest.mark.asyncio
    async def test_rate_limited_append_is_not_retried(self):
        def respond(n, request):
            if request.method == "POST":
                return httpx.Response(429, headers={"Retry-After": str(MAX_RETRY_AFTER_SECONDS + 1)}, json={})
            return httpx.Response(201, json={})

        transport, calls = _recording_transport(respond)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await SpotifyService(access_token="t", client=client).replace_playlist_items("p1", _uris(150))

        assert exc_info.value.response.status_code == 429
        assert calls == [("PUT", 100), ("POST", 50)]

    @pytest.mark.asyncio
    async def test_small_replace_is_a_single_put(self):
        transport, calls = _recording_transport(lambda n, request: httpx.Response(201, json={}))
        async with httpx.AsyncClient(transport=transport) as client:
            await SpotifyService(access_token="t", client=client).replace_playlist_items("p1", [])

        assert calls == [("PUT", 0)]


class TestRetryAfterAboveTheCapFailsFast:
    @pytest.mark.asyncio
    async def test_long_retry_after_raises_the_429_without_sleeping(self):
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(429, headers={"Retry-After": "600"}, json={})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = SpotifyService(access_token="t", client=client)
            with (
                patch("app.services.spotify.asyncio.sleep", new=AsyncMock()) as sleep_mock,
                pytest.raises(httpx.HTTPStatusError) as exc_info,
            ):
                await service._request_with_retry(client, "GET", ITEMS_URL)

        assert exc_info.value.response.status_code == 429
        assert len(requests) == 1
        sleep_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_after_at_the_cap_is_still_slept_through(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": str(MAX_RETRY_AFTER_SECONDS)}, json={})
            return httpx.Response(200, json={"ok": True})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = SpotifyService(access_token="t", client=client)
            with patch("app.services.spotify.asyncio.sleep", new=AsyncMock()) as sleep_mock:
                resp = await service._request_with_retry(client, "GET", ITEMS_URL)

        assert resp.status_code == 200
        sleep_mock.assert_awaited_once_with(MAX_RETRY_AFTER_SECONDS)


def _http_error(status: int, method: str = "GET") -> httpx.HTTPStatusError:
    request = httpx.Request(method, ITEMS_URL)
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"{status} error", request=request, response=response)


def _classify(errors: list[str], exceptions: list[BaseException], attempted: int = 2, failed: int = 1):
    return scheduler._classify_failure(
        playlists_attempted=attempted,
        playlists_failed=failed,
        error_messages=errors,
        exceptions=exceptions,
    )


class TestClassifyFailureIgnoresMessageText:
    def test_a_playlist_named_top_401_is_not_an_expired_token(self):
        assert _classify(["Top 401: Episodes could not be fetched for: Show"], []) == "partial"

    def test_a_429_in_a_name_is_not_a_rate_limit(self):
        assert _classify(["Route 429 Too Many Requests: boom"], [RuntimeError("boom")]) == "partial"

    def test_status_is_read_through_the_cause_chain(self):
        try:
            try:
                raise _http_error(429)
            except httpx.HTTPStatusError as e:
                raise EpisodeFetchError("Show: rate limited") from e
        except EpisodeFetchError as wrapped:
            assert _classify(["Daily: Show: rate limited"], [wrapped]) == "rate_limit"

    def test_401_status_is_token_expired(self):
        assert _classify(["x"], [_http_error(401)]) == "token_expired"

    def test_failed_write_status_is_playlist_write_failed(self):
        assert _classify(["x"], [_http_error(500, "PUT")]) == "playlist_write_failed"

    def test_no_failures_is_none(self):
        assert _classify([], [], failed=0) is None


class TestUpdateResultCarriesTheException:
    @pytest.mark.asyncio
    async def test_failed_update_keeps_the_exception_for_classification(self):
        playlist = MagicMock()
        playlist.is_enabled = True
        playlist.name = "Top 401"
        builder = PlaylistBuilder(AsyncMock(), MagicMock(), token_manager=MagicMock())
        error = _http_error(429, "PUT")
        builder._ensure_spotify_playlist = AsyncMock(side_effect=error)

        result = await builder.update_playlist(playlist)

        assert result.success is False
        assert result.exception is error


class TestDailyUpdateMisfireGrace:
    @pytest.mark.asyncio
    async def test_daily_job_has_a_misfire_grace_and_coalesces(self):
        fake_scheduler = MagicMock()
        fake_scheduler.running = False

        with (
            patch.object(scheduler, "fail_orphaned_sync_logs", AsyncMock(return_value=0)),
            patch.object(scheduler, "_load_update_times", AsyncMock(return_value=[(3, 0), (15, 30)])),
            patch.object(scheduler, "scheduler", fake_scheduler),
        ):
            await scheduler.init_scheduler()

        daily = next(c for c in fake_scheduler.add_job.call_args_list if c.kwargs.get("id") == "daily_playlist_update")
        assert daily.kwargs["misfire_grace_time"] == scheduler.DAILY_UPDATE_MISFIRE_GRACE_SECONDS >= 60
        assert daily.kwargs["coalesce"] is True


class TestBuilderSharesOneHttpClient:
    @pytest.mark.asyncio
    async def test_every_request_in_a_build_uses_the_same_client_and_it_is_closed(self):
        token_manager = MagicMock()
        token_manager.get_token = AsyncMock(return_value="token")
        builder = PlaylistBuilder(AsyncMock(), MagicMock(), token_manager=token_manager)
        seen: list[httpx.AsyncClient | None] = []

        async def fake_update(playlist):
            for _ in range(2):
                spotify = await builder._get_spotify_client()
                seen.append(spotify._client)
            return MagicMock()

        builder._update_playlist = fake_update
        playlists = MagicMock()
        playlists.scalars.return_value.all.return_value = [MagicMock(), MagicMock()]
        builder._db.execute = AsyncMock(return_value=playlists)

        await builder.update_all_playlists()

        assert len(seen) == 4
        assert seen[0] is not None and all(client is seen[0] for client in seen)
        assert seen[0].is_closed
        assert builder._spotify._client is None
