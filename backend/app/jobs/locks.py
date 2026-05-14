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

playlist_write_lock = asyncio.Lock()
