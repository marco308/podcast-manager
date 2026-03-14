"""Application configuration using Pydantic Settings."""

from functools import lru_cache

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
        "playlist-modify-public "
        "playlist-modify-private"
    )

    # Security
    ENCRYPTION_KEY: str  # Fernet key for token encryption
    SECRET_KEY: str  # Session/JWT secret

    # Frontend URL for redirects
    FRONTEND_URL: str = "http://localhost:5173"

    # Cookie domain for cross-subdomain sharing (e.g., ".marcuslab.uk")
    # Leave empty for same-origin cookies (local development)
    COOKIE_DOMAIN: str = ""

    # Scheduler
    PLAYLIST_UPDATE_HOUR: int = 4
    PLAYLIST_UPDATE_MINUTE: int = 0

    def spotify_auth_url(self, state: str) -> str:
        """Build Spotify authorization URL with OAuth state parameter."""
        import urllib.parse

        params = {
            "client_id": self.SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.SPOTIFY_REDIRECT_URI,
            "scope": self.SPOTIFY_SCOPES,
            "show_dialog": "true",
            "state": state,
        }
        return f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(params)}"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
