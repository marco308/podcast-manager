"""Tests for scripts.adopt_legacy_schema (issue #168).

The script may only stamp a database at head when its schema really is the
shape head produces. An old-shape or partially-migrated database must be
rejected with a non-zero exit so the container entrypoint fails loudly.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

import app.models  # noqa: F401  — registers every model on Base.metadata
from app.database import Base
from scripts.adopt_legacy_schema import schema_gaps

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _create_all(db_path: Path) -> None:
    """Provision the schema the way the pre-#149 app did on startup."""
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def _run_script(db_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    return subprocess.run(
        [sys.executable, "-m", "scripts.adopt_legacy_schema"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


def _stamped_revision(db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as conn:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:
            return None
    return row[0] if row else None


def test_schema_gaps_empty_for_create_all_database(tmp_path: Path) -> None:
    db = tmp_path / "full.db"
    _create_all(db)
    engine = create_engine(f"sqlite:///{db}")
    try:
        assert schema_gaps(engine) == []
    finally:
        engine.dispose()


def test_schema_gaps_reports_missing_table_and_column(tmp_path: Path) -> None:
    db = tmp_path / "old_shape.db"
    _create_all(db)
    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE podcasts DROP COLUMN unplayed_episodes"))
            conn.execute(text("DROP TABLE app_settings"))
            conn.commit()
        gaps = schema_gaps(engine)
    finally:
        engine.dispose()
    assert "table 'app_settings'" in gaps
    assert "column podcasts.unplayed_episodes" in gaps


def test_empty_database_is_left_for_alembic(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    result = _run_script(db)
    assert result.returncode == 0, result.stderr
    assert _stamped_revision(db) is None


def test_legacy_create_all_database_is_stamped_at_head(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _create_all(db)
    result = _run_script(db)
    assert result.returncode == 0, result.stderr
    assert _stamped_revision(db) is not None


def test_old_shape_database_is_rejected(tmp_path: Path) -> None:
    """Missing schema objects must abort with a non-zero exit, not stamp."""
    db = tmp_path / "old_shape.db"
    _create_all(db)
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE podcasts DROP COLUMN unplayed_episodes")
        conn.commit()

    result = _run_script(db)
    assert result.returncode == 1, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Refusing to adopt" in result.stderr
    assert _stamped_revision(db) is None
