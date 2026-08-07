"""Regression tests for the migration chain (issue #176).

Runs Alembic in a subprocess against a scratch SQLite database so nothing
leaks into the test process (settings are cached process-wide).

Covers:
  * upgrade head -> downgrade base completes — 005's downgrade used to drop
    ``podcasts.unplayed_episodes`` unconditionally after 013's downgrade had
    already dropped it, stranding the database mid-downgrade;
  * 007's downgrade converts a single-element ``categories`` list back to its
    value — the old SQL hit ``INSTR(...) = 0``, so ``SUBSTR(x, 2, -2)`` read
    backwards and corrupted every single-category podcast to ``'['``;
  * the migrated schema at head matches the models (scripts.check_migration_drift).
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run_module(db_path, "alembic", *args)


def _run_module(db_path: Path, module: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


def _assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, f"exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"


def test_upgrade_head_then_downgrade_base_completes(tmp_path: Path) -> None:
    """The full chain must unwind cleanly; 005 used to fail on a double drop."""
    db = tmp_path / "chain.db"
    _assert_ok(_run_alembic(db, "upgrade", "head"))
    _assert_ok(_run_alembic(db, "downgrade", "base"))

    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "podcasts" not in tables, "downgrade base should drop the schema"


def test_migrated_schema_matches_models(tmp_path: Path) -> None:
    """scripts.check_migration_drift must pass on a freshly migrated database."""
    db = tmp_path / "drift.db"
    _assert_ok(_run_alembic(db, "upgrade", "head"))
    _assert_ok(_run_module(db, "scripts.check_migration_drift"))


def test_007_downgrade_preserves_single_category(tmp_path: Path) -> None:
    """'["news"]' must come back as 'news', not '[' (issue #176)."""
    db = tmp_path / "categories.db"
    _assert_ok(_run_alembic(db, "upgrade", "007_multi_category"))

    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO podcasts (spotify_id, name, is_sequential, is_weekend_only, categories) "
            "VALUES (?, ?, 0, 0, ?)",
            [
                ("s1", "Single", '["news"]'),
                ("s2", "Empty", "[]"),
                ("s3", "Multi", '["primary", "news"]'),
            ],
        )
        conn.commit()

    _assert_ok(_run_alembic(db, "downgrade", "006_add_sessions"))

    with sqlite3.connect(db) as conn:
        rows = dict(conn.execute("SELECT spotify_id, category FROM podcasts"))
    assert rows == {"s1": "news", "s2": "none", "s3": "primary"}
