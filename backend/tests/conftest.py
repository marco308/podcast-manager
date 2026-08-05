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
os.environ.setdefault("SECRET_KEY", "test-secret-key")
