"""Reconcile the local podcast library against the user's Spotify library.

One place owns the walk over ``GET /me/shows`` and the subscription
reconcile, so the manual ``POST /podcasts/sync`` and the daily job can't
drift apart (issue #240). The logic here is the endpoint's, moved: the
snapshot checks and the grace period are issue #155's and unchanged.

A show that has left the library is *marked* (``missing_since``) and only
deleted after :data:`UNSUBSCRIBE_GRACE`, because deleting cascades to the
show's playlist assignments and a paginated walk can never prove a single
show is gone. Marking has an immediate effect of its own:
``PlaylistBuilder._get_playlist_podcasts`` skips a marked show, so it stops
contributing episodes the moment it goes missing rather than at the end of
the grace period (issue #240).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.podcast import Podcast
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)

# Page size for GET /me/shows; 50 is Spotify's maximum.
SHOWS_PAGE_LIMIT = 50

# How long a show must stay absent from GET /me/shows before its row (and its
# playlist assignments) are deleted (issue #155). Spans many syncs, so a run
# that loses a page can't retire anything on its own.
UNSUBSCRIBE_GRACE = timedelta(days=7)


@dataclass
class LibrarySyncResult:
    """Outcome of one reconciliation pass."""

    synced: int = 0
    new: int = 0
    missing: int = 0
    removed: int = 0
    # False when the walk didn't look like a snapshot, so nothing was marked
    # or retired (see _reconcile_subscriptions). The upserts still happened.
    reconciled: bool = True

    @property
    def summary(self) -> str:
        """One-line description for logs and SyncLog details."""
        parts = [f"{self.synced} synced", f"{self.new} new"]
        if self.missing:
            parts.append(f"{self.missing} no longer subscribed")
        if self.removed:
            parts.append(f"{self.removed} removed")
        if not self.reconciled:
            parts.append("subscription check skipped (incomplete walk)")
        return ", ".join(parts)


async def sync_library(
    db: AsyncSession,
    spotify: SpotifyService,
    *,
    on_unauthorized: Callable[[str | None], Awaitable[str]] | None = None,
) -> LibrarySyncResult:
    """Sync the ``podcasts`` table from the user's subscribed Spotify shows.

    Upserts every show in ``GET /me/shows``, then marks or retires the local
    podcasts the walk did not see. The caller commits.

    Args:
        db: Database session. Left uncommitted on return.
        spotify: Authenticated Spotify client.
        on_unauthorized: Optional 401-recovery callback (usually
            ``TokenManager.force_refresh``), passed to every page request.

    Returns:
        Counts for the pass. ``reconciled`` is False if the walk was not
        trusted enough to mark anything.

    Raises:
        Exception: whatever the Spotify walk raises. Nothing is reconciled on
            a partial walk — the caller decides whether to keep the upserts
            done so far (they are still pending in ``db``).
    """
    result = LibrarySyncResult()

    # Spotify pagination can hand back the same show on two pages (the list
    # shifts under us mid-sync). With autoflush off, the existence SELECT
    # can't see the first pending insert, so a repeat would 500 the whole
    # sync on the unique constraint — skip anything already seen (issue #182).
    # The same set is what the subscription reconcile compares against.
    seen_spotify_ids: set[str] = set()
    # Spotify's reported library size, and whether it held still for the whole
    # walk. A total that moves mid-walk means the library changed underneath
    # us, so the pages don't add up to a snapshot of anything (issue #155).
    reported_total: int | None = None
    total_changed = False
    offset = 0

    while True:
        shows_data = await spotify.get_user_shows(
            limit=SHOWS_PAGE_LIMIT, offset=offset, on_unauthorized=on_unauthorized
        )
        items = shows_data.get("items", [])
        page_total = shows_data.get("total")
        if isinstance(page_total, int):
            if reported_total is not None and page_total != reported_total:
                total_changed = True
            reported_total = page_total

        if not items:
            break

        for item in items:
            show = item.get("show", {})
            spotify_id = show.get("id")

            if not spotify_id or spotify_id in seen_spotify_ids:
                continue
            seen_spotify_ids.add(spotify_id)

            await _upsert_show(db, show, spotify_id, result)

        offset += SHOWS_PAGE_LIMIT

        # Check if there are more pages
        if len(items) < SHOWS_PAGE_LIMIT:
            break

    await _reconcile_subscriptions(db, seen_spotify_ids, None if total_changed else reported_total, result)
    return result


async def _upsert_show(
    db: AsyncSession,
    show: dict,
    spotify_id: str,
    result: LibrarySyncResult,
) -> None:
    """Insert or refresh one show's row, clearing any pending unsubscribe mark."""
    existing = await db.execute(select(Podcast).where(Podcast.spotify_id == spotify_id))
    podcast = existing.scalar_one_or_none()

    # Spotify returns images largest-first; take the largest available.
    images = show.get("images", [])
    image_url = images[0]["url"] if images else None

    # No per-show episode fetch here (issue #155). This used to call
    # GET /shows/{id}/episodes for *every* subscribed show — one extra
    # API call each, against the same rate-limit budget the cleanup
    # job is careful with — and then extrapolate an unplayed count
    # from the newest 50 episodes. Spotify returns episodes
    # newest-first, so the sample was systematically the least-played
    # and the estimate ran high, yet it was stored and displayed as a
    # real number. unplayed_episodes is now maintained by the playlist
    # build, which already fetches full episode lists with
    # resume_point and can count exactly.
    if podcast:
        # Update existing podcast; leave unplayed_episodes alone.
        podcast.name = show.get("name", podcast.name)
        podcast.description = show.get("description")
        podcast.image_url = image_url
        podcast.publisher = show.get("publisher")
        podcast.total_episodes = show.get("total_episodes", 0)
        podcast.last_synced_at = datetime.now(UTC)
        # Still subscribed: clear any pending unsubscribe mark. The
        # assignments were never dropped, so the show returns to its
        # playlists exactly as it was.
        podcast.missing_since = None
    else:
        # Create new podcast. unplayed_episodes stays NULL ("not
        # counted") until a playlist build reads the whole show.
        podcast = Podcast(
            spotify_id=spotify_id,
            name=show.get("name", "Unknown"),
            description=show.get("description"),
            image_url=image_url,
            publisher=show.get("publisher"),
            total_episodes=show.get("total_episodes", 0),
            last_synced_at=datetime.now(UTC),
        )
        db.add(podcast)
        result.new += 1

    result.synced += 1


async def _reconcile_subscriptions(
    db: AsyncSession,
    seen_spotify_ids: set[str],
    reported_total: int | None,
    result: LibrarySyncResult,
) -> None:
    """Retire podcasts that have left the user's Spotify library (issue #155).

    Deleting a podcast cascades to its playlist assignments, so absence has to
    be earned. ``GET /me/shows`` is paginated and the library can change
    underneath the walk: a page can come back short, a show can slip between
    pages, and the reported ``total`` shifts with it — cardinality alone never
    proves a given show is gone. So a show missing from a walk is only
    *marked* (``missing_since``), and is deleted once it has been missing for
    ``UNSUBSCRIBE_GRACE``, which spans many syncs. Anything that reappears
    has its mark cleared by the upsert loop.

    The walk still has to look complete before anything is marked. Fewer
    distinct shows than Spotify's ``total`` means pages were lost; so does a
    ``total`` that moved between pages (the caller passes ``None`` for that),
    which is how a library that shrinks mid-walk would otherwise hand back a
    short page whose smaller total the already-seen IDs satisfy. Marking on
    either would start the clock on shows that never left.
    """
    if reported_total is None or not seen_spotify_ids or len(seen_spotify_ids) < reported_total:
        logger.warning(
            "Skipping subscription reconcile: saw %d shows, Spotify reported %s",
            len(seen_spotify_ids),
            reported_total,
        )
        result.reconciled = False
        return

    now = datetime.now(UTC)
    missing_result = await db.execute(select(Podcast).where(Podcast.spotify_id.not_in(seen_spotify_ids)))
    missing = missing_result.scalars().all()

    for podcast in missing:
        if podcast.missing_since is None:
            podcast.missing_since = now
            logger.info(
                "Podcast %s (%s) is no longer subscribed; removing if still absent in %s",
                podcast.name,
                podcast.spotify_id,
                UNSUBSCRIBE_GRACE,
            )
        elif now - podcast.missing_since >= UNSUBSCRIBE_GRACE:
            logger.info(
                "Removing podcast %s (%s): unsubscribed since %s",
                podcast.name,
                podcast.spotify_id,
                podcast.missing_since,
            )
            await db.delete(podcast)
            result.removed += 1

    result.missing = len(missing) - result.removed
