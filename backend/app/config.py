"""Application configuration using Pydantic Settings."""

import urllib.parse
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "Podcast Manager"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/podcast_manager.db"

    # Spotify OAuth
    SPOTIFY_CLIENT_ID: str
    SPOTIFY_CLIENT_SECRET: str
    SPOTIFY_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"
    SPOTIFY_SCOPES: str = (
        "user-read-playback-position "
        "user-library-read "
        "user-library-modify "
        # Reading private playlists is what lets the link picker list the
        # ones the user owns, and the ownership check see them (issue #245).
        "playlist-read-private "
        "playlist-modify-public "
        "playlist-modify-private"
    )

    # Security
    ENCRYPTION_KEY: str  # Fernet key for token encryption

    # Frontend URL for redirects
    FRONTEND_URL: str = "http://localhost:5173"

    # Cookie domain for cross-subdomain sharing (e.g., ".example.com")
    # Leave empty for same-origin cookies (local development)
    COOKIE_DOMAIN: str = ""

    # Scheduler
    PLAYLIST_UPDATE_HOUR: int = 4
    PLAYLIST_UPDATE_MINUTE: int = 0

    @field_validator("FRONTEND_URL")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        """Normalise FRONTEND_URL so it can be used as a CORS origin.

        A browser's ``Origin`` header never carries a trailing slash, so
        ``https://app.example.com/`` would never match and every API call
        would fail preflight — while the OAuth redirect kept working,
        because it stripped the slash locally (issue #157).
        """
        return value.rstrip("/")

    def spotify_auth_url(self, state: str, code_challenge: str) -> str:
        """Build Spotify authorization URL with OAuth state + PKCE challenge.

        PKCE (RFC 7636) binds this authorization request to the upcoming
        token exchange: whoever intercepts the authorization code still
        needs the `code_verifier` we hold server-side to redeem it.
        """
        params = {
            "client_id": self.SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.SPOTIFY_REDIRECT_URI,
            "scope": self.SPOTIFY_SCOPES,
            "show_dialog": "true",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(params)}"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
