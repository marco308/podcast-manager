"""Reconcile the local podcast library against the user's Spotify library.

One place owns the walk over ``GET /me/shows``, so the manual
``POST /podcasts/sync`` and the daily job can't drift apart (issue #240).

The sync is a reconciliation, not an upsert: a podcast the user has
unfollowed on Spotify is stamped with ``unfollowed_at`` and stops
contributing episodes to builds. Stamping rather than deleting is deliberate
— deleting would cascade the show's playlist assignments away, and a single
sync run that silently loses a page (or a Spotify hiccup between pages)
would then be unrecoverable. A stamp is reversible: the next run that sees
the show again clears it and the assignments are intact.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.podcast import Podcast
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)

# Page size for GET /me/shows; 50 is Spotify's maximum.
SHOWS_PAGE_LIMIT = 50


@dataclass
class LibrarySyncResult:
    """Outcome of one reconciliation pass."""

    synced: int = 0
    new: int = 0
    unfollowed: int = 0
    refollowed: int = 0
    # False when the unfollow reconciliation was deliberately skipped (see
    # _reconcile_unfollows); the upserts still happened.
    reconciled: bool = True

    @property
    def summary(self) -> str:
        """One-line description for logs and SyncLog details."""
        parts = [f"{self.synced} synced", f"{self.new} new"]
        if self.unfollowed:
            parts.append(f"{self.unfollowed} unfollowed")
        if self.refollowed:
            parts.append(f"{self.refollowed} re-followed")
        if not self.reconciled:
            parts.append("unfollow check skipped (empty library response)")
        return ", ".join(parts)


async def sync_library(db: AsyncSession, spotify: SpotifyService) -> LibrarySyncResult:
    """Sync the ``podcasts`` table from the user's subscribed Spotify shows.

    Upserts every show in ``GET /me/shows`` and then stamps every local
    podcast the walk did not see as unfollowed. The caller commits.

    Args:
        db: Database session. Left uncommitted on return.
        spotify: Authenticated Spotify client.

    Returns:
        Counts for the pass. ``reconciled`` is False if the unfollow check
        was skipped.

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
    # The same set is what the unfollow reconciliation compares against.
    seen_spotify_ids: set[str] = set()
    offset = 0

    while True:
        shows_data = await spotify.get_user_shows(limit=SHOWS_PAGE_LIMIT, offset=offset)
        items = shows_data.get("items", [])

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

    await _reconcile_unfollows(db, seen_spotify_ids, result)
    return result


async def _upsert_show(
    db: AsyncSession,
    show: dict,
    spotify_id: str,
    result: LibrarySyncResult,
) -> None:
    """Insert or refresh one show's row, clearing any stale unfollow stamp."""
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
        if podcast.unfollowed_at is not None:
            # Followed again (or the previous run's stamp was a false
            # positive). The assignments were never dropped, so clearing the
            # stamp restores the show to builds exactly as it was.
            podcast.unfollowed_at = None
            result.refollowed += 1
    else:
        # Create new podcast. unplayed_episodes starts at 0 and is
        # filled in by the next playlist build.
        podcast = Podcast(
            spotify_id=spotify_id,
            name=show.get("name", "Unknown"),
            description=show.get("description"),
            image_url=image_url,
            publisher=show.get("publisher"),
            total_episodes=show.get("total_episodes", 0),
            unplayed_episodes=0,
            last_synced_at=datetime.now(UTC),
        )
        db.add(podcast)
        result.new += 1

    result.synced += 1


async def _reconcile_unfollows(
    db: AsyncSession,
    seen_spotify_ids: set[str],
    result: LibrarySyncResult,
) -> None:
    """Stamp every local podcast the Spotify walk did not return.

    One guard: an empty library response against a non-empty local library is
    treated as a glitch rather than "the user unfollowed everything". Stamping
    there would take every playlist down to nothing on the very next build,
    and the one thing an empty response cannot distinguish is a broken read
    from a real mass unfollow. Nothing is stamped and the next run decides.
    """
    if not seen_spotify_ids:
        followed = await db.execute(select(func.count()).select_from(Podcast).where(Podcast.unfollowed_at.is_(None)))
        if (followed.scalar() or 0) > 0:
            logger.warning(
                "Spotify returned an empty show library while podcasts are still followed locally; "
                "skipping the unfollow reconciliation for this run"
            )
            result.reconciled = False
            return

    query = select(Podcast).where(Podcast.unfollowed_at.is_(None))
    if seen_spotify_ids:
        query = query.where(Podcast.spotify_id.not_in(seen_spotify_ids))

    stale = await db.execute(query)
    now = datetime.now(UTC)
    for podcast in stale.scalars().all():
        podcast.unfollowed_at = now
        result.unfollowed += 1
        logger.info(f"Podcast '{podcast.name}' is no longer followed on Spotify; flagged as unfollowed")
