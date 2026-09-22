"""Short-lived exchange codes for the mobile OAuth callback.

The old mobile flow sent `session_id` and `csrf_token` back to the iOS app
via query string on a `podcastmanager://` redirect. Custom URL schemes
aren't exclusive — any app can register the same scheme and intercept the
redirect — and query strings also land in device logs / crash reports.

The replacement: the backend creates the session as before, but returns an
opaque `exchange_code` in the callback URL instead of the credentials.
The app then POSTs that code to `/api/auth/mobile-exchange` and receives
`session_id` + `csrf_token` in the JSON response body, which never
appears in any URL. The code is single-use and expires in ~2 minutes.

Storage is in-process: single backend replica, tight TTL, a restart just
forces a retry. Move to Redis if the stack ever grows past one replica.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

EXCHANGE_CODE_TTL = timedelta(minutes=2)


@dataclass(frozen=True)
class PendingExchange:
    """Session credentials waiting to be handed to the mobile app."""

    session_id: str
    csrf_token: str
    expires_at: datetime


_pending: dict[str, PendingExchange] = {}
_lock = asyncio.Lock()


async def issue_exchange_code(session_id: str, csrf_token: str) -> str:
    """Store credentials under a one-time code and return the code.

    Opportunistically sweeps expired entries on each call so the dict
    can't grow unbounded if the endpoint is scraped.
    """
    code = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    async with _lock:
        _pending[code] = PendingExchange(
            session_id=session_id,
            csrf_token=csrf_token,
            expires_at=now + EXCHANGE_CODE_TTL,
        )
        # Sweep expired entries.
        expired = [k for k, v in _pending.items() if v.expires_at < now]
        for k in expired:
            del _pending[k]
    return code


async def redeem_exchange_code(code: str) -> PendingExchange | None:
    """Pop and return the pending exchange if it's still valid.

    Returns None if the code is unknown or expired. The entry is removed
    either way — codes are strictly single-use.
    """
    async with _lock:
        pending = _pending.pop(code, None)
    if pending is None:
        return None
    if pending.expires_at < datetime.now(UTC):
        return None
    return pending
