"""Process-wide locks shared between scheduled jobs and manual triggers.

Issue #89, PR3. The cleanup job (``remove_played_episodes_from_playlists``)
and the rebuild job (``update_all_playlists``) both issue Spotify writes
against the same playlists. Two writers racing is what produced the
"playlists half-rebuilt / half-cleaned" symptom in the original bug.

We deploy as a **single Docker Swarm replica** today, so a module-level
:class:`asyncio.Lock` is sufficient — there is exactly one event loop
and one process holding the lock. If we ever scale to multiple replicas
this needs to be swapped for a DB advisory lease (e.g.
``SELECT pg_try_advisory_lock(...)`` on Postgres) or a Redis lock. The
contract — "only one writer to a user's playlists at a time" — stays
the same; only the locking primitive changes.

The same lock is taken by the manual ``POST /playlists/{id}/run`` and
``POST /playlists/run-all`` endpoints so a button-press from the UI
serialises against scheduled work too (issue #89, AC #3).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

playlist_write_lock = asyncio.Lock()

# Serialises the library sync (``services/library_sync.sync_library``) between
# the daily job and ``POST /podcasts/sync`` (issue #240). Two concurrent walks
# of ``GET /me/shows`` both see "no row" for a newly-followed show and both
# insert it; the second commit then dies on the ``spotify_id`` unique
# constraint and takes the whole sync with it — the cross-request twin of the
# intra-request duplicate fixed in issue #182. Serialising also stops two full
# library walks from spending the same rate-limit budget twice over.
#
# Same single-replica assumption as ``playlist_write_lock`` above.
library_sync_lock = asyncio.Lock()


class AccountWriteGate:
    """Lets state-changing requests run concurrently until an account delete.

    Account deletion (issue #266) must not interleave with a request that has
    already validated its session: a ``POST /api/playlists`` in flight would
    insert its row after the user is gone. With SQLite's foreign keys off,
    that row would be orphaned, and since SQLite reuses the freed user id,
    the next account to register would inherit it. The job locks above
    don't help, because ordinary API writes never take them.

    Every mutating request holds the gate shared for its whole run
    (``AccountWriteGateMiddleware`` in ``main.py``). The delete closes it,
    which holds back new writes, and waits for in-flight ones to drain. The
    held-back requests then validate against a deleted session and get 401.

    Same single-replica assumption as the locks above.
    """

    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._active = 0
        self._closed = False

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[None]:
        async with self._cond:
            await self._cond.wait_for(lambda: not self._closed)
            self._active += 1
        try:
            yield
        finally:
            async with self._cond:
                self._active -= 1
                self._cond.notify_all()

    @asynccontextmanager
    async def exclusive(self, timeout: float) -> AsyncIterator[None]:
        """Close the gate and wait for in-flight writes to finish.

        Raises ``TimeoutError`` if they don't within ``timeout`` seconds, or
        if another delete already holds the gate; the gate is then reopened.
        """
        async with self._cond:
            if self._closed:
                raise TimeoutError("account write gate already closed")
            self._closed = True
            try:
                await asyncio.wait_for(self._cond.wait_for(lambda: self._active == 0), timeout)
            except TimeoutError:
                self._closed = False
                self._cond.notify_all()
                raise
        try:
            yield
        finally:
            async with self._cond:
                self._closed = False
                self._cond.notify_all()


account_write_gate = AccountWriteGate()
