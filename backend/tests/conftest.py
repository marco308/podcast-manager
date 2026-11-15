"""Test environment bootstrap.

Settings requires Spotify/crypto values at construction time; provide dummy
values so the suite runs without a real .env (locally and in CI). Real env
vars would still win, so none of these leak into a configured environment.
"""

import os

# 32 url-safe base64 bytes — a structurally valid Fernet key.
_DUMMY_FERNET_KEY = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE="

os.environ.setdefault("SPOTIFY_CLIENT_ID", "test-client-id")
os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("ENCRYPTION_KEY", _DUMMY_FERNET_KEY)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_spotify_rate_window():
    """Empty the process-wide Spotify throttle window around every test.

    The window is shared by every ``SpotifyService`` (issue #314), so without
    this one test's requests would throttle the next.
    """
    from app.services import spotify

    spotify._shared_request_timestamps.clear()
    yield
    spotify._shared_request_timestamps.clear()
