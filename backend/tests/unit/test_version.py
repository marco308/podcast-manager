"""The version comes from backend/VERSION, the one place it lives."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import _read_version, get_settings
from app.main import app

VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def test_version_is_read_from_the_version_file():
    assert _read_version() == VERSION_FILE.read_text().strip()
    assert _read_version() == get_settings().APP_VERSION


def test_health_reports_version_and_commit():
    body = TestClient(app).get("/api/health").json()
    assert body["version"] == VERSION_FILE.read_text().strip()
    assert "commit" in body
