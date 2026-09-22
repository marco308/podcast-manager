"""Integration tests for token freshness across a playlist update.

Issue #89: simulate the exact scenario from the bug — a long GET phase
(say, an hour fetching show episodes) that lets the in-memory token go
stale, then assert the subsequent PUT picks up a fresh bearer token
rather than reusing the original.

"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.spotify import SpotifyService
from app.services.token_manager import TokenManager


@pytest.mark.asyncio
async def test_request_with_retry_recovers_from_401_via_callback():
    """A 401 with on_unauthorized set should trigger one retry on a fresh token."""
    call_log: list[tuple[str, str]] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        call_log.append((request.method, auth))
        if auth == "Bearer stale":
            return httpx.Response(401, json={"error": {"status": 401, "message": "expired"}})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(_handler)
    callback = AsyncMock(return_value="fresh")
    async with httpx.AsyncClient(transport=transport) as client:
        service = SpotifyService(access_token="stale", client=client)
        response = await service._request_with_retry(
            client,
            "PUT",
            "https://api.spotify.com/v1/playlists/p1/items",
            headers={"Authorization": "Bearer stale"},
            json={"uris": ["spotify:episode:abc"]},
            on_unauthorized=callback,
        )

    assert response.status_code == 200
    callback.assert_awaited_once()
    assert call_log == [("PUT", "Bearer stale"), ("PUT", "Bearer fresh")]


@pytest.mark.asyncio
async def test_long_get_then_put_uses_fresh_token():
    """Cached token decrypted before a long GET phase must NOT reach the PUT.

    The bug from #89: GET /shows/{id}/episodes streamed for an hour, then
    the PUT /playlists/{id}/items reused the original bearer and got 401.
    With the TokenManager wiring in place, the PUT must observe the
    refreshed token.
    """
    # User row: token has just expired (was valid an "hour ago" at the
    # start of the GET phase).
    user = MagicMock()
    user.id = 42
    user.access_token = "enc:stale-token"
    user.refresh_token = "enc:rt"
    user.token_expires_at = datetime.now(UTC) - timedelta(minutes=10)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def execute(self, _stmt):
            r = MagicMock()
            r.scalar_one_or_none.return_value = user
            return r

        async def commit(self):
            return None

    enc = MagicMock()
    enc.decrypt.side_effect = lambda c: c.removeprefix("enc:")
    enc.encrypt.side_effect = lambda p: f"enc:{p}"

    refresh_mock = AsyncMock(
        return_value={
            "access_token": "fresh-token",
            "refresh_token": "rotated-rt",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        }
    )

    seen_auth_on_put: list[str] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            seen_auth_on_put.append(request.headers.get("Authorization", ""))
            return httpx.Response(200, json={"snapshot_id": "abc"})
        return httpx.Response(200, json={"items": []})

    TokenManager._user_locks.clear()

    with (
        patch("app.services.token_manager.async_session_maker", _FakeSession),
        patch("app.services.token_manager.get_encryption_service", return_value=enc),
        patch("app.services.token_manager.SpotifyService.refresh_access_token", refresh_mock),
    ):
        tm = TokenManager(user_id=user.id)

        # Fresh-token check immediately before the write should refresh
        # — the cached token is already expired.
        token_for_write = await tm.get_token(min_remaining_seconds=300)
        assert token_for_write == "fresh-token"

        transport = httpx.MockTransport(_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = SpotifyService(access_token=token_for_write, client=client)
            await service.replace_playlist_items(
                "playlist-id",
                ["spotify:episode:1"],
                on_unauthorized=tm.force_refresh,
            )

    assert seen_auth_on_put == ["Bearer fresh-token"], (
        "PUT must use the refreshed bearer, not the stale one captured at job start"
    )
    refresh_mock.assert_awaited()  # at least once for the just-in-time refresh
