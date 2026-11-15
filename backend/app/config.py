"""Application configuration using Pydantic Settings."""

import urllib.parse
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_version() -> str:
    """The release version, from ``backend/VERSION``.

    That file is the one place the version lives. The release workflow
    refuses a tag that doesn't match it, so bump it in the release-notes PR.
    """
    try:
        return (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


# Where a Docker/Swarm secret named ``metrics_token`` is mounted.
DOCKER_METRICS_TOKEN_SECRET = Path("/run/secrets/metrics_token")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "Podcast Manager"
    APP_VERSION: str = _read_version()
    # The commit the image was built from. CI passes it as a build arg; a
    # local build leaves it "unknown".
    GIT_SHA: str = "unknown"
    DEBUG: bool = False
    # Log every SQL statement. Separate from DEBUG so turning on debug logging
    # doesn't also turn this on; bound parameters are never logged either way
    # (the engine uses hide_parameters), since they include session-ID hashes
    # and CSRF tokens.
    SQL_ECHO: bool = False
    # "json" (one JSON object per line) or "text". Unset: text with DEBUG,
    # json otherwise; see ``log_format``.
    LOG_FORMAT: str = ""

    # Bearer token for GET /metrics. Empty: /metrics answers 404, as if the
    # route didn't exist. Read from the environment first, then from the file
    # named by METRICS_TOKEN_FILE, then from the Docker secret
    # /run/secrets/metrics_token if one is mounted.
    METRICS_TOKEN: str = ""
    METRICS_TOKEN_FILE: str = ""

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

    # The Spotify user ID allowed to sign in. When set, any other account is
    # refused at the OAuth callback, including the very first sign-in, so a
    # fresh deployment can't be claimed by whoever reaches it first. Empty
    # keeps the old rule: the first account to sign in becomes the owner.
    OWNER_SPOTIFY_ID: str = ""

    # Scheduler
    PLAYLIST_UPDATE_HOUR: int = 4
    PLAYLIST_UPDATE_MINUTE: int = 0
    # IANA zone the run times are wall-clock times in (e.g. "Europe/London").
    # Defaults to UTC, which is what the scheduler used before this was
    # configurable, so existing deployments keep their run times.
    TIMEZONE: str = "UTC"

    @field_validator("TIMEZONE")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        """Fail at startup on a zone name the scheduler couldn't use."""
        value = value.strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(
                f"TIMEZONE={value!r} is not a known IANA time zone name (e.g. 'UTC', 'Europe/London')"
            ) from e
        return value

    @field_validator("LOG_FORMAT")
    @classmethod
    def _valid_log_format(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("", "json", "text"):
            raise ValueError(f"LOG_FORMAT={value!r} must be 'json' or 'text'")
        return value

    @property
    def log_format(self) -> str:
        """The effective log format: LOG_FORMAT, else text locally (DEBUG) and json in production."""
        return self.LOG_FORMAT or ("text" if self.DEBUG else "json")

    @model_validator(mode="after")
    def _metrics_token_from_file(self) -> "Settings":
        """Fill METRICS_TOKEN from a secret file when the environment leaves it empty.

        An explicitly named METRICS_TOKEN_FILE that can't be read fails
        startup; the default Docker secret path is only used if it exists.
        """
        if self.METRICS_TOKEN.strip():
            self.METRICS_TOKEN = self.METRICS_TOKEN.strip()
            return self
        if self.METRICS_TOKEN_FILE:
            path = Path(self.METRICS_TOKEN_FILE)
            try:
                self.METRICS_TOKEN = path.read_text().strip()
            except OSError as e:
                raise ValueError(f"METRICS_TOKEN_FILE={self.METRICS_TOKEN_FILE!r} could not be read") from e
        elif DOCKER_METRICS_TOKEN_SECRET.is_file():
            self.METRICS_TOKEN = DOCKER_METRICS_TOKEN_SECRET.read_text().strip()
        return self

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
