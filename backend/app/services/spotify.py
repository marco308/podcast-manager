"""Spotify Web API client service."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

MAX_RETRIES = 3


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

    @property
    def _headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def _request_with_retry(self, client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
        """Make an HTTP request with automatic retry on 429 rate limit.

        Retries up to MAX_RETRIES times, respecting Spotify's Retry-After header.

        Args:
            client: The httpx client to use.
            method: HTTP method (GET, POST, PUT, DELETE).
            url: Request URL.
            **kwargs: Additional arguments passed to the request.

        Returns:
            The HTTP response.
        """
        response = await client.request(method, url, **kwargs)
        for attempt in range(MAX_RETRIES - 1):
            if response.status_code != 429:
                break
            retry_after = int(response.headers.get("Retry-After", "5"))
            logger.warning(f"Rate limited by Spotify (attempt {attempt + 2}/{MAX_RETRIES}), waiting {retry_after}s")
            await asyncio.sleep(retry_after)
            response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    async def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access and refresh tokens.

        Args:
            code: The authorization code from Spotify OAuth callback.

        Returns:
            Dictionary containing access_token, refresh_token, expires_in.
        """
        async with self._get_client_contextmanager() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._settings.SPOTIFY_REDIRECT_URI,
                },
                auth=(
                    self._settings.SPOTIFY_CLIENT_ID,
                    self._settings.SPOTIFY_CLIENT_SECRET,
                ),
            )
            response.raise_for_status()
            data = response.json()

            # Calculate absolute expiration time
            expires_at = datetime.now(UTC) + timedelta(seconds=data["expires_in"])

            return {
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
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
            response = await client.get(
                f"{SPOTIFY_API_BASE}/me",
                headers=self._headers,
            )
            response.raise_for_status()
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

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Get a playlist by ID.

        Args:
            playlist_id: Spotify playlist ID.

        Returns:
            Playlist data.
        """
        async with self._get_client_contextmanager() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def create_playlist(self, name: str, description: str = "", public: bool = False) -> dict[str, Any]:
        """Create a new playlist.

        Args:
            name: Playlist name.
            description: Playlist description.
            public: Whether the playlist should be public.

        Returns:
            Created playlist data.
        """
        async with self._get_client_contextmanager() as client:
            response = await client.post(
                f"{SPOTIFY_API_BASE}/me/playlists",
                headers=self._headers,
                json={
                    "name": name,
                    "description": description,
                    "public": public,
                },
            )
            response.raise_for_status()
            return response.json()

    async def replace_playlist_items(self, playlist_id: str, uris: list[str]) -> None:
        """Replace all items in a playlist.

        Args:
            playlist_id: Spotify playlist ID.
            uris: List of Spotify URIs (e.g., spotify:episode:xxx).
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
                )
            else:
                # First replace with first 100
                await self._request_with_retry(
                    client,
                    "PUT",
                    f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items",
                    headers=self._headers,
                    json={"uris": uris[:100]},
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
                    )

    async def remove_tracks_from_playlist(self, playlist_id: str, uris: list[str]) -> None:
        """Remove tracks from a playlist.

        Args:
            playlist_id: Spotify playlist ID.
            uris: List of Spotify URIs to remove (e.g., spotify:episode:xxx).
        """
        import json as _json

        async with self._get_client_contextmanager() as client:
            body = _json.dumps({"items": [{"uri": uri} for uri in uris]})
            await self._request_with_retry(
                client,
                "DELETE",
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items",
                headers={**self._headers, "Content-Type": "application/json"},
                content=body,
            )

    async def get_playlist_tracks(self, playlist_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
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
            )
            return resp.json()

    async def get_episodes(self, episode_ids: list[str]) -> list[dict[str, Any]]:
        """Get multiple episodes by IDs using individual fetches with rate limiting.

        The batch GET /episodes endpoint was deprecated by Spotify in Feb 2026
        for Dev Mode apps, so we fetch individually with concurrency control.

        Args:
            episode_ids: List of Spotify episode IDs.

        Returns:
            List of episode data.
        """
        if not episode_ids:
            return []

        # Fetch sequentially to avoid Spotify 429 rate limits
        results: list[dict[str, Any] | None] = []

        async with self._get_client_contextmanager() as client:
            for episode_id in episode_ids:
                try:
                    resp = await self._request_with_retry(
                        client,
                        "GET",
                        f"{SPOTIFY_API_BASE}/episodes/{episode_id}",
                        headers=self._headers,
                        params={"market": "from_token"},
                    )
                    results.append(resp.json())
                except Exception:
                    logger.warning("Failed to fetch episode %s, skipping", episode_id)
                    results.append(None)

        return [ep for ep in results if ep is not None]

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
