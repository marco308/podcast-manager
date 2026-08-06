"""Spotify Web API client service."""

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

MAX_RETRIES = 3

# Sliding-window soft throttle. We track the last 30 seconds of request
# timestamps and back off briefly when we cross the threshold — keeps us
# well under Spotify's actual 429 line without bursting.
RATE_LIMIT_WINDOW_SECONDS = 30.0
RATE_LIMIT_THRESHOLD = 150
SOFT_THROTTLE_SLEEP_SECONDS = 0.1

# In ``cleanup_mode``, we abort the run if Spotify asks us to wait longer
# than this — the daily rebuild has priority and we don't want a stuck
# cleanup loop holding the rate-limit budget hostage.
CLEANUP_MODE_RETRY_AFTER_LIMIT = 60


class CleanupBudgetExceeded(Exception):
    """Raised when a cleanup-mode request hits a Retry-After above the cleanup limit.

    The 5-minute cleanup loop must yield to the daily rebuild rather than
    sleep for minutes; the scheduler catches this and finalises the run
    with a clear SyncLog entry (issue #89).
    """


class SpotifyService:
    """Async client for Spotify Web API.

    Can be used as an async context manager to reuse a single httpx.AsyncClient
    across multiple calls, reducing connection overhead::

        async with SpotifyService(access_token=token) as spotify:
            shows = await spotify.get_user_shows()
            episodes = await spotify.get_show_episodes(show_id)

    When used without the context manager, each method creates (and closes) its
    own client for backward compatibility.
    """

    def __init__(self, access_token: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        """Initialize Spotify service.

        Args:
            access_token: Optional access token for authenticated requests.
            client: Optional shared httpx.AsyncClient to reuse across calls.
        """
        self._access_token = access_token
        self._settings = get_settings()
        self._client = client
        self._owns_client = False

        # Sliding-window throttle state (issue #89, PR2). Per-instance so
        # each user's SpotifyService tracks its own budget — Spotify
        # rate-limits per access token, not globally.
        self._request_timestamps: deque[float] = deque()
        self.api_calls_used: int = 0

    async def __aenter__(self) -> "SpotifyService":
        """Enter async context manager, creating a shared client if needed."""
        if self._client is None:
            self._client = httpx.AsyncClient()
            self._owns_client = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context manager, closing the client if we own it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
            self._owns_client = False

    def _get_client_contextmanager(self) -> "_ClientContextManager":
        """Return a context manager that yields the shared client or a new one."""
        return _ClientContextManager(self._client)

    def reset_api_counter(self) -> None:
        """Zero the per-run API-call counter.

        Called by the cleanup scheduler at the start of each run so the
        SyncLog reflects only that run's traffic. Does not clear the
        sliding-window deque — the actual rate-limit budget should
        carry across runs (Spotify doesn't reset because we did).
        """
        self.api_calls_used = 0

    async def _throttle_if_needed(self) -> None:
        """Soft-throttle before issuing a request if the sliding window is hot.

        Drops timestamps older than ``RATE_LIMIT_WINDOW_SECONDS`` from the
        front of the deque, then — if we still hold more than
        ``RATE_LIMIT_THRESHOLD`` — sleeps briefly to let the window
        slide. Cheap to call on every request.
        """
        now = time.monotonic()
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        while self._request_timestamps and self._request_timestamps[0] < cutoff:
            self._request_timestamps.popleft()

        if len(self._request_timestamps) >= RATE_LIMIT_THRESHOLD:
            await asyncio.sleep(SOFT_THROTTLE_SLEEP_SECONDS)

    @property
    def _headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def _issue_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Soft-throttle, count, then issue a single request.

        Centralised so the 429-retry path and the 401-retry path both
        contribute to ``api_calls_used`` and both feed the sliding
        window — otherwise a retry storm wouldn't register as traffic.
        """
        await self._throttle_if_needed()
        self._request_timestamps.append(time.monotonic())
        self.api_calls_used += 1
        return await client.request(method, url, **kwargs)

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        on_unauthorized: Callable[[], Awaitable[str]] | None = None,
        cleanup_mode: bool = False,
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request with automatic retry on 429 rate limit.

        Issues at most MAX_RETRIES attempts in total (one initial request plus
        MAX_RETRIES - 1 retries), respecting Spotify's Retry-After header.

        If ``on_unauthorized`` is provided and the server responds 401, the
        callback is invoked to obtain a fresh bearer token, the
        ``Authorization`` header on the request is rewritten, and the request
        is retried **once** (not part of the normal retry loop). Without the
        callback, 401 stays a hard failure — existing behaviour.

        In ``cleanup_mode`` (issue #89, PR2) a 429 with ``Retry-After`` above
        :data:`CLEANUP_MODE_RETRY_AFTER_LIMIT` raises
        :class:`CleanupBudgetExceeded` instead of sleeping — the cleanup
        loop should yield to the daily rebuild rather than hold the
        budget for minutes.

        Args:
            client: The httpx client to use.
            method: HTTP method (GET, POST, PUT, DELETE).
            url: Request URL.
            on_unauthorized: Optional async callback returning a new bearer
                token. Used to recover from token expiry that happens
                between the in-memory check and the API call (issue #89).
            cleanup_mode: When True, bail out on long Retry-After waits
                instead of sleeping.
            **kwargs: Additional arguments passed to the request.

        Returns:
            The HTTP response.

        Raises:
            CleanupBudgetExceeded: ``cleanup_mode=True`` and Spotify
                returned 429 with Retry-After above the cleanup limit.
        """
        response = await self._issue_request(client, method, url, **kwargs)
        for attempt in range(MAX_RETRIES - 1):
            if response.status_code != 429:
                break
            raw_retry_after = int(response.headers.get("Retry-After", "5"))

            if cleanup_mode and raw_retry_after > CLEANUP_MODE_RETRY_AFTER_LIMIT:
                # The daily rebuild has priority; surface this so the
                # scheduler can finalise the run with a SyncLog row.
                raise CleanupBudgetExceeded(
                    f"Spotify Retry-After {raw_retry_after}s exceeds cleanup limit {CLEANUP_MODE_RETRY_AFTER_LIMIT}s"
                )

            retry_after = min(raw_retry_after, 300)  # Cap at 5 minutes
            if raw_retry_after > 300:
                logger.warning(f"Spotify requested {raw_retry_after}s wait — capping to {retry_after}s")
            logger.warning(f"Rate limited by Spotify (attempt {attempt + 2}/{MAX_RETRIES}), waiting {retry_after}s")
            await asyncio.sleep(retry_after)
            response = await self._issue_request(client, method, url, **kwargs)

        # Single 401 recovery attempt: refresh the token via the callback and
        # retry once. We do this AFTER the 429 loop so a rate-limited refresh
        # doesn't burn the one retry.
        if response.status_code == 401 and on_unauthorized is not None:
            logger.warning("Spotify 401 — refreshing token and retrying once")
            new_token = await on_unauthorized()
            headers = dict(kwargs.get("headers") or {})
            headers["Authorization"] = f"Bearer {new_token}"
            kwargs["headers"] = headers
            response = await self._issue_request(client, method, url, **kwargs)

        response.raise_for_status()
        return response

    async def exchange_code_for_tokens(self, code: str, code_verifier: str | None = None) -> dict[str, Any]:
        """Exchange authorization code for access and refresh tokens.

        Args:
            code: The authorization code from Spotify OAuth callback.
            code_verifier: PKCE code verifier that matches the `code_challenge`
                sent on the authorize request. Required whenever the authorize
                call included a challenge.

        Returns:
            Dictionary containing access_token, refresh_token, expires_in.
        """
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._settings.SPOTIFY_REDIRECT_URI,
        }
        if code_verifier is not None:
            data["code_verifier"] = code_verifier

        async with self._get_client_contextmanager() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data=data,
                auth=(
                    self._settings.SPOTIFY_CLIENT_ID,
                    self._settings.SPOTIFY_CLIENT_SECRET,
                ),
            )
            response.raise_for_status()
            payload = response.json()

            # Calculate absolute expiration time
            expires_at = datetime.now(UTC) + timedelta(seconds=payload["expires_in"])

            return {
                "access_token": payload["access_token"],
                "refresh_token": payload["refresh_token"],
                "expires_at": expires_at,
            }

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token using a refresh token.

        Args:
            refresh_token: The refresh token.

        Returns:
            Dictionary containing new access_token and expires_at.
        """
        async with self._get_client_contextmanager() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                auth=(
                    self._settings.SPOTIFY_CLIENT_ID,
                    self._settings.SPOTIFY_CLIENT_SECRET,
                ),
            )
            response.raise_for_status()
            data = response.json()

            expires_at = datetime.now(UTC) + timedelta(seconds=data["expires_in"])

            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),
                "expires_at": expires_at,
            }

    async def get_current_user(self) -> dict[str, Any]:
        """Get the current user's Spotify profile.

        Returns:
            User profile data from Spotify.
        """
        async with self._get_client_contextmanager() as client:
            response = await self._request_with_retry(
                client,
                "GET",
                f"{SPOTIFY_API_BASE}/me",
                headers=self._headers,
            )
            return response.json()

    async def get_user_shows(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get user's saved/subscribed podcasts (shows).

        Args:
            limit: Maximum number of shows to return (max 50).
            offset: Index of the first show to return.

        Returns:
            Paginated list of saved shows.
        """
        async with self._get_client_contextmanager() as client:
            resp = await self._request_with_retry(
                client,
                "GET",
                f"{SPOTIFY_API_BASE}/me/shows",
                headers=self._headers,
                params={"limit": limit, "offset": offset},
            )
            return resp.json()

    async def get_show_episodes(self, show_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get episodes for a specific show.

        Args:
            show_id: Spotify show ID.
            limit: Maximum number of episodes to return (max 50).
            offset: Index of the first episode to return.

        Returns:
            Paginated list of episodes.
        """
        async with self._get_client_contextmanager() as client:
            resp = await self._request_with_retry(
                client,
                "GET",
                f"{SPOTIFY_API_BASE}/shows/{show_id}/episodes",
                headers=self._headers,
                params={
                    "limit": limit,
                    "offset": offset,
                    "market": "from_token",
                },
            )
            return resp.json()

    async def create_playlist(
        self,
        name: str,
        description: str = "",
        public: bool = False,
        *,
        on_unauthorized: Callable[[], Awaitable[str]] | None = None,
    ) -> dict[str, Any]:
        """Create a new playlist.

        Args:
            name: Playlist name.
            description: Playlist description.
            public: Whether the playlist should be public.
            on_unauthorized: Optional callback to recover from 401 by
                refreshing the bearer token and retrying once.

        Returns:
            Created playlist data.
        """
        async with self._get_client_contextmanager() as client:
            response = await self._request_with_retry(
                client,
                "POST",
                f"{SPOTIFY_API_BASE}/me/playlists",
                headers=self._headers,
                json={
                    "name": name,
                    "description": description,
                    "public": public,
                },
                on_unauthorized=on_unauthorized,
            )
            return response.json()

    async def replace_playlist_items(
        self,
        playlist_id: str,
        uris: list[str],
        *,
        on_unauthorized: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        """Replace all items in a playlist.

        Args:
            playlist_id: Spotify playlist ID.
            uris: List of Spotify URIs (e.g., spotify:episode:xxx).
            on_unauthorized: Optional callback to recover from 401 by
                refreshing the bearer token and retrying once (issue #89).
        """
        async with self._get_client_contextmanager() as client:
            # Spotify limits to 100 items per request
            if len(uris) <= 100:
                await self._request_with_retry(
                    client,
                    "PUT",
                    f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items",
                    headers=self._headers,
                    json={"uris": uris},
                    on_unauthorized=on_unauthorized,
                )
            else:
                # First replace with first 100
                await self._request_with_retry(
                    client,
                    "PUT",
                    f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items",
                    headers=self._headers,
                    json={"uris": uris[:100]},
                    on_unauthorized=on_unauthorized,
                )

                # Then add remaining in batches of 100
                for i in range(100, len(uris), 100):
                    batch = uris[i : i + 100]
                    await self._request_with_retry(
                        client,
                        "POST",
                        f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items",
                        headers=self._headers,
                        json={"uris": batch},
                        on_unauthorized=on_unauthorized,
                    )

    async def remove_tracks_from_playlist(
        self,
        playlist_id: str,
        uris: list[str],
        *,
        on_unauthorized: Callable[[], Awaitable[str]] | None = None,
        cleanup_mode: bool = False,
    ) -> None:
        """Remove tracks from a playlist.

        Args:
            playlist_id: Spotify playlist ID.
            uris: List of Spotify URIs to remove (e.g., spotify:episode:xxx).
            on_unauthorized: Optional callback to recover from 401 by
                refreshing the bearer token and retrying once (issue #89).
            cleanup_mode: When True, abort on long Retry-After waits (PR2).
        """
        async with self._get_client_contextmanager() as client:
            body = json.dumps({"items": [{"uri": uri} for uri in uris]})
            await self._request_with_retry(
                client,
                "DELETE",
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items",
                headers={**self._headers, "Content-Type": "application/json"},
                content=body,
                on_unauthorized=on_unauthorized,
                cleanup_mode=cleanup_mode,
            )

    async def get_playlist_tracks(
        self,
        playlist_id: str,
        limit: int = 50,
        offset: int = 0,
        *,
        cleanup_mode: bool = False,
    ) -> dict[str, Any]:
        """Get all tracks/episodes in a playlist.

        Args:
            playlist_id: Spotify playlist ID.
            limit: Maximum number of tracks to return (max 50).
            offset: Index of the first track to return.

        Returns:
            Paginated list of tracks in the playlist.

        Note:
            Spotify playlist items wrap episodes in a ``track`` key (not ``item``).
            The ``fields`` parameter requests ``track(uri,...)`` accordingly.
        """
        async with self._get_client_contextmanager() as client:
            resp = await self._request_with_retry(
                client,
                "GET",
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items",
                headers=self._headers,
                params={
                    "limit": limit,
                    "offset": offset,
                    "fields": "items(track(uri,resume_point(fully_played))),next,total",
                },
                cleanup_mode=cleanup_mode,
            )
            return resp.json()

    async def get_show_episodes_all(self, show_id: str, max_episodes: int = 200) -> list[dict[str, Any]]:
        """Get all episodes for a show with pagination.

        Args:
            show_id: Spotify show ID.
            max_episodes: Maximum number of episodes to fetch.

        Returns:
            List of episodes.
        """
        all_episodes = []
        offset = 0

        while len(all_episodes) < max_episodes:
            batch_limit = min(50, max_episodes - len(all_episodes))
            data = await self.get_show_episodes(show_id, limit=batch_limit, offset=offset)

            episodes = data.get("items", [])
            if not episodes:
                break

            all_episodes.extend(episodes)
            offset += len(episodes)

            if not data.get("next"):
                break

        return all_episodes

    async def get_all_user_shows(self) -> list[dict[str, Any]]:
        """Get all user's subscribed podcasts (handles pagination).

        Returns:
            Complete list of all saved shows.
        """
        all_shows = []
        offset = 0
        limit = 50

        while True:
            data = await self.get_user_shows(limit=limit, offset=offset)
            items = data.get("items", [])

            if not items:
                break

            all_shows.extend(items)
            offset += len(items)

            if not data.get("next"):
                break

        return all_shows

    async def unfollow_show(self, show_id: str) -> None:
        """Unfollow/remove a show from the user's library.

        Args:
            show_id: Spotify show ID to unfollow.

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        async with self._get_client_contextmanager() as client:
            await self._request_with_retry(
                client,
                "DELETE",
                f"{SPOTIFY_API_BASE}/me/shows",
                headers=self._headers,
                params={"ids": show_id},
            )


class _ClientContextManager:
    """Helper that yields an existing client or creates a temporary one."""

    def __init__(self, shared_client: httpx.AsyncClient | None) -> None:
        self._shared = shared_client
        self._temp: httpx.AsyncClient | None = None

    async def __aenter__(self) -> httpx.AsyncClient:
        if self._shared is not None:
            return self._shared
        self._temp = httpx.AsyncClient()
        return self._temp

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._temp is not None:
            await self._temp.aclose()
            self._temp = None
