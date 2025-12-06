"""Spotify Web API client service."""

from datetime import datetime, timedelta
from typing import Any

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
            response = await client.post(
                f"{SPOTIFY_API_BASE}/users/{user_id}/playlists",
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
            response = await client.put(
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
                headers=self._headers,
                json={"uris": uris},
            )
            response.raise_for_status()
