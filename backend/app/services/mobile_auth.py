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

On its own that code is a bearer token: whoever sees the callback URL inside
those two minutes can redeem it. So the app binds it PKCE-style (issue #307).
It sends ``code_challenge = BASE64URL(SHA256(code_verifier))`` to
``/api/auth/login``, the challenge is stored with the pending exchange, and
the code is only redeemable together with the verifier, which never leaves
the app until the exchange itself. Installed builds that predate this send
no challenge and their codes stay redeemable without a verifier; drop that
once those builds are gone.

Storage is in-process: single backend replica, tight TTL, a restart just
forces a retry. Move to Redis if the stack ever grows past one replica.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

EXCHANGE_CODE_TTL = timedelta(minutes=2)

# BASE64URL(SHA256(...)) without padding is always 43 characters.
_CODE_CHALLENGE_RE = re.compile(r"[A-Za-z0-9_-]{43}")
# RFC 7636 section 4.1: 43 to 128 unreserved characters.
_CODE_VERIFIER_RE = re.compile(r"[A-Za-z0-9._~-]{43,128}")


def is_valid_code_challenge(challenge: str) -> bool:
    """Whether ``challenge`` has the shape of an S256 PKCE challenge."""
    return _CODE_CHALLENGE_RE.fullmatch(challenge) is not None


def _challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class PendingExchange:
    """Session credentials waiting to be handed to the mobile app."""

    session_id: str
    csrf_token: str
    expires_at: datetime
    # S256 challenge the app sent to /login; None for builds without PKCE.
    code_challenge: str | None = None


_pending: dict[str, PendingExchange] = {}
_lock = asyncio.Lock()


async def issue_exchange_code(session_id: str, csrf_token: str, code_challenge: str | None = None) -> str:
    """Store credentials under a one-time code and return the code.

    With a ``code_challenge`` the code can only be redeemed together with the
    verifier that hashes to it.

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
            code_challenge=code_challenge,
        )
        # Sweep expired entries.
        expired = [k for k, v in _pending.items() if v.expires_at < now]
        for k in expired:
            del _pending[k]
    return code


async def redeem_exchange_code(code: str, code_verifier: str | None = None) -> PendingExchange | None:
    """Pop and return the pending exchange if it's still valid.

    Returns None if the code is unknown or expired, or if it was issued with
    a challenge and ``code_verifier`` is missing or doesn't hash to it. The
    entry is removed either way — codes are strictly single-use, so a wrong
    verifier burns the code rather than leaving it open to further guesses.
    """
    async with _lock:
        pending = _pending.pop(code, None)
    if pending is None:
        return None
    if pending.expires_at < datetime.now(UTC):
        return None
    if pending.code_challenge is not None:
        if code_verifier is None or _CODE_VERIFIER_RE.fullmatch(code_verifier) is None:
            return None
        if not secrets.compare_digest(_challenge_for(code_verifier), pending.code_challenge):
            return None
    return pending
