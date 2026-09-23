"""Mint a long-lived session for local testing, so no browser login is needed.

The Spotify side already survives restarts: the user row holds an encrypted
refresh token and ``TokenManager`` renews the access token on demand. What
expires is the app session (24 hours). This script creates a fresh session row
for the single user in the local database and writes it where tools can pick
it up:

- ``data/dev-session/cookies.txt`` — a Netscape cookie jar for ``curl -b``
- ``data/dev-session/session.json`` — ``session_id`` and ``csrf_token``

Log in through the browser once against the local server first; after that,
rerun this whenever the session lapses. Refuses to run unless
``SPOTIFY_REDIRECT_URI`` points at 127.0.0.1/localhost, so it can't mint a
session against a production database by accident.

Usage (from ``backend/``)::

    python -m scripts.dev_session [--days 30]
    curl -k -b data/dev-session/cookies.txt https://127.0.0.1:8000/api/auth/me
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_maker, engine
from app.models.session import Session
from app.models.user import User
from app.services.session import SessionService, hash_session_id

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
OUT_DIR = Path("data/dev-session")


async def mint(days: int) -> int:
    """Create the session and write it out. Returns an exit code."""
    settings = get_settings()
    host = urlparse(settings.SPOTIFY_REDIRECT_URI).hostname
    if host not in LOCAL_HOSTS:
        print(f"Refusing: SPOTIFY_REDIRECT_URI host is {host!r}, not a local address.", file=sys.stderr)
        return 1

    async with async_session_maker() as db:
        users = (await db.execute(select(User))).scalars().all()
        if len(users) != 1:
            names = ", ".join(u.spotify_id for u in users) or "none"
            print(
                f"Expected exactly one user in the local database, found {len(users)} ({names}). "
                "Log in once through the browser against a fresh local database.",
                file=sys.stderr,
            )
            return 1
        user = users[0]

        now = datetime.now(UTC)
        session_id = SessionService.generate_session_id()
        session = Session(
            session_id_hash=hash_session_id(session_id),
            user_id=user.id,
            csrf_token=SessionService.generate_csrf_token(),
            expires_at=now + timedelta(days=days),
            last_accessed_at=now,
        )
        db.add(session)
        await db.commit()

    await engine.dispose()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    expiry = int(session.expires_at.timestamp())
    # Host-only cookies for 127.0.0.1; the "#HttpOnly_" prefix is curl's marker.
    jar = OUT_DIR / "cookies.txt"
    jar.write_text(
        "# Netscape HTTP Cookie File\n"
        f"#HttpOnly_127.0.0.1\tFALSE\t/\tTRUE\t{expiry}\tsession_id\t{session_id}\n"
        f"127.0.0.1\tFALSE\t/\tTRUE\t{expiry}\tcsrf_token\t{session.csrf_token}\n"
    )
    info = OUT_DIR / "session.json"
    info.write_text(
        json.dumps(
            {
                "spotify_id": user.spotify_id,
                "session_id": session_id,
                "csrf_token": session.csrf_token,
                "expires_at": session.expires_at.isoformat(),
            },
            indent=2,
        )
        + "\n"
    )
    for path in (jar, info):
        path.chmod(0o600)

    print(f"Session for {user.spotify_id} valid until {session.expires_at:%Y-%m-%d %H:%M} UTC")
    print(f"  cookie jar: {jar}")
    print(f"  details:    {info}")
    return 0


def main() -> int:
    """Parse arguments and mint the session."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30, help="session lifetime in days (default 30)")
    args = parser.parse_args()
    return asyncio.run(mint(args.days))


if __name__ == "__main__":
    sys.exit(main())
