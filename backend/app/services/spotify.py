"""Spotify Web API client service."""

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyService:
    """Async client for Spotify Web API."""

    def __init__(self, access_token: str | None = None) -> None:
        """Initialize Spotify service.

        Args:
            access_token: Optional access token for authenticated requests.
        """
        self._access_token = access_token
        self._settings = get_settings()

    @property
    def _headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def exchange_code_for_tokens(
        self, code: str
    ) -> dict[str, Any]:
        """Exchange authorization code for access and refresh tokens.

        Args:
            code: The authorization code from Spotify OAuth callback.

        Returns:
            Dictionary containing access_token, refresh_token, expires_in.
        """
        async with httpx.AsyncClient() as client:
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
            expires_at = datetime.utcnow() + timedelta(seconds=data["expires_in"])

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
        async with httpx.AsyncClient() as client:
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

            expires_at = datetime.utcnow() + timedelta(seconds=data["expires_in"])

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
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/me",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def get_user_shows(
        self, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get user's saved/subscribed podcasts (shows).

        Args:
            limit: Maximum number of shows to return (max 50).
            offset: Index of the first show to return.

        Returns:
            Paginated list of saved shows.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/me/shows",
                headers=self._headers,
                params={"limit": limit, "offset": offset},
            )
            response.raise_for_status()
            return response.json()

    async def get_show_episodes(
        self, show_id: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get episodes for a specific show.

        Args:
            show_id: Spotify show ID.
            limit: Maximum number of episodes to return (max 50).
            offset: Index of the first episode to return.

        Returns:
            Paginated list of episodes.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/shows/{show_id}/episodes",
                headers=self._headers,
                params={"limit": limit, "offset": offset},
            )
            response.raise_for_status()
            return response.json()

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Get a playlist by ID.

        Args:
            playlist_id: Spotify playlist ID.

        Returns:
            Playlist data.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def create_playlist(
        self, user_id: str, name: str, description: str = "", public: bool = False
    ) -> dict[str, Any]:
        """Create a new playlist.

        Args:
            user_id: Spotify user ID.
            name: Playlist name.
            description: Playlist description.
            public: Whether the playlist should be public.

        Returns:
            Created playlist data.
        """
        async with httpx.AsyncClient() as client:
            # URL-encode the user_id to handle special characters like #
            encoded_user_id = quote(user_id, safe="")
            response = await client.post(
                f"{SPOTIFY_API_BASE}/users/{encoded_user_id}/playlists",
                headers=self._headers,
                json={
                    "name": name,
                    "description": description,
                    "public": public,
                },
            )
            response.raise_for_status()
            return response.json()

    async def replace_playlist_items(
        self, playlist_id: str, uris: list[str]
    ) -> None:
        """Replace all items in a playlist.

        Args:
            playlist_id: Spotify playlist ID.
            uris: List of Spotify URIs (e.g., spotify:episode:xxx).
        """
        async with httpx.AsyncClient() as client:
            # Spotify limits to 100 items per request
            if len(uris) <= 100:
                response = await client.put(
                    f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
                    headers=self._headers,
                    json={"uris": uris},
                )
                response.raise_for_status()
            else:
                # First replace with first 100
                response = await client.put(
                    f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
                    headers=self._headers,
                    json={"uris": uris[:100]},
                )
                response.raise_for_status()

                # Then add remaining in batches of 100
                for i in range(100, len(uris), 100):
                    batch = uris[i : i + 100]
                    response = await client.post(
                        f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
                        headers=self._headers,
                        json={"uris": batch},
                    )
                    response.raise_for_status()

    async def remove_tracks_from_playlist(
        self, playlist_id: str, uris: list[str]
    ) -> None:
        """Remove tracks from a playlist.

        Args:
            playlist_id: Spotify playlist ID.
            uris: List of Spotify URIs to remove (e.g., spotify:episode:xxx).
        """
        import json as _json

        async with httpx.AsyncClient() as client:
            # Some httpx/delete implementations don't accept `json` kwarg.
            # Send raw JSON in the request body via `content` instead.
            body = _json.dumps({"tracks": [{"uri": uri} for uri in uris]})
            response = await client.delete(
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
                headers={**self._headers, "Content-Type": "application/json"},
                content=body,
            )
            response.raise_for_status()

    async def get_playlist_tracks(
        self, playlist_id: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get all tracks/episodes in a playlist.

        Args:
            playlist_id: Spotify playlist ID.
            limit: Maximum number of tracks to return (max 50).
            offset: Index of the first track to return.

        Returns:
            Paginated list of tracks in the playlist.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
                headers=self._headers,
                params={
                    "limit": limit,
                    "offset": offset,
                    "fields": "items(track(uri,resume_point(fully_played))),next,total",
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_episode(self, episode_id: str) -> dict[str, Any]:
        """Get a single episode by ID.

        Args:
            episode_id: Spotify episode ID.

        Returns:
            Episode data including resume_point if available.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SPOTIFY_API_BASE}/episodes/{episode_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def get_episodes(self, episode_ids: list[str]) -> list[dict[str, Any]]:
        """Get multiple episodes by IDs.

        Args:
            episode_ids: List of Spotify episode IDs (max 50).

        Returns:
            List of episode data.
        """
        if not episode_ids:
            return []

        async with httpx.AsyncClient() as client:
            # Spotify allows up to 50 episodes per request
            response = await client.get(
                f"{SPOTIFY_API_BASE}/episodes",
                headers=self._headers,
                params={"ids": ",".join(episode_ids[:50])},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("episodes", [])

    async def get_show_episodes_all(
        self, show_id: str, max_episodes: int = 200
    ) -> list[dict[str, Any]]:
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
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{SPOTIFY_API_BASE}/me/shows",
                headers=self._headers,
                params={"ids": show_id},
            )
            response.raise_for_status()
