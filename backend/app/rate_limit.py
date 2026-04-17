"""Per-session rate limiting for expensive endpoints.

The heavy endpoints (sync, run-all, manual playlist rebuild) either burn
Spotify API quota or write-storm the local DB. A compromised session or a
buggy client could call them in a tight loop and cause real damage. These
limits keep the blast radius small without getting in the way of normal use.

We key on the session cookie so each authenticated session gets its own
budget; unauthenticated requests fall back to client IP.
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

_SESSION_COOKIE = "session_id"


def _rate_limit_key(request: Request) -> str:
    """Prefer the session cookie as the rate-limit bucket.

    Falls back to remote address for unauthenticated requests (e.g. the
    login redirect). Using the session ID means a single user's limits
    don't bleed into a shared-NAT neighbour's.
    """
    session_id = request.cookies.get(_SESSION_COOKIE)
    if session_id:
        return f"session:{session_id}"
    return f"ip:{get_remote_address(request)}"


# In-memory storage is fine here — single backend replica, and we don't need
# strict cross-restart accuracy for rate limits. Switch to Redis if/when the
# stack grows beyond one replica.
limiter = Limiter(key_func=_rate_limit_key)
