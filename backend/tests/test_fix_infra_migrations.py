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
  * the migrated schema at head matches the models (scripts.check_migration_drift);
  * 020 hashes existing session IDs in place, so signed-in clients stay signed in.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run_module(db_path, "alembic", *args)


def _run_module(db_path: Path, module: str, *args: str) -> subprocess.CompletedProcess[str]:
    return _run_python_args(db_path, "-m", module, *args)


def _run_python(db_path: Path, code: str) -> subprocess.CompletedProcess[str]:
    return _run_python_args(db_path, "-c", code)


def _run_python_args(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    return subprocess.run(
        [sys.executable, *args],
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


def test_016_clears_counts_on_upgrade_and_restores_zero_on_downgrade(tmp_path: Path) -> None:
    """Counts written before 016 are fabricated (extrapolated from the newest
    50 episodes) and indistinguishable from real ones, so the upgrade must
    clear every one of them — leaving a stale value would put an invented
    number back in front of the user (issue #155)."""
    db = tmp_path / "unplayed.db"
    _assert_ok(_run_alembic(db, "upgrade", "015_podcast_is_archived"))

    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO podcasts (spotify_id, name, total_episodes, unplayed_episodes, is_sequential) "
            "VALUES (?, ?, ?, ?, 0)",
            [("s1", "Extrapolated", 500, 312), ("s2", "Zero", 10, 0)],
        )
        conn.commit()

    _assert_ok(_run_alembic(db, "upgrade", "016_unplayed_episodes_nullable"))

    with sqlite3.connect(db) as conn:
        rows = dict(conn.execute("SELECT spotify_id, unplayed_episodes FROM podcasts"))
    assert rows == {"s1": None, "s2": None}

    _assert_ok(_run_alembic(db, "downgrade", "015_podcast_is_archived"))

    with sqlite3.connect(db) as conn:
        rows = dict(conn.execute("SELECT spotify_id, unplayed_episodes FROM podcasts"))
        nullable = {row[1]: not row[3] for row in conn.execute("PRAGMA table_info(podcasts)")}
    assert rows == {"s1": 0, "s2": 0}
    assert nullable["unplayed_episodes"] is False, "downgrade must restore NOT NULL"


_SESSION_LOOKUP = """
import asyncio
from app.database import async_session_maker
from app.services.session import SessionService

async def main():
    async with async_session_maker() as db:
        for sid in ("plain-web", "plain-ios"):
            session = await SessionService().get_session(db, sid)
            assert session is not None and session.user_id == 1, sid
        assert await SessionService().get_session(db, "nope") is None

asyncio.run(main())
"""


def test_020_hashes_existing_session_ids_in_place(tmp_path: Path) -> None:
    """Signed-in clients (web and iOS) must stay signed in across 020: their
    plaintext cookie has to find the row once it only holds the hash."""
    db = tmp_path / "sessions.db"
    _assert_ok(_run_alembic(db, "upgrade", "019_podcast_unplayed_counted_at"))

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO users (id, spotify_id, access_token, refresh_token, token_expires_at) "
            "VALUES (1, 'me', 'a', 'r', '2099-01-01 00:00:00')"
        )
        conn.executemany(
            "INSERT INTO sessions (session_id, user_id, csrf_token, expires_at) VALUES (?, 1, ?, ?)",
            [("plain-web", "csrf-web", "2099-01-01 00:00:00"), ("plain-ios", "csrf-ios", "2099-01-01 00:00:00")],
        )
        conn.commit()

    _assert_ok(_run_alembic(db, "upgrade", "head"))

    with sqlite3.connect(db) as conn:
        rows = dict(conn.execute("SELECT csrf_token, session_id FROM sessions"))
    assert rows == {
        "csrf-web": hashlib.sha256(b"plain-web").hexdigest(),
        "csrf-ios": hashlib.sha256(b"plain-ios").hexdigest(),
    }

    # The app's own lookup finds them by the plaintext cookie value.
    _assert_ok(_run_python(db, _SESSION_LOOKUP))

    # Hashes can't be reversed, so downgrade signs everyone out.
    _assert_ok(_run_alembic(db, "downgrade", "019_podcast_unplayed_counted_at"))
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone() == (0,)
