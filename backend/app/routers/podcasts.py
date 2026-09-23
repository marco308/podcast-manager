"""Podcasts router for managing podcast metadata."""

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jobs import locks
from app.models.playlist_podcast import PlaylistPodcast
from app.models.podcast import Podcast
from app.models.session import Session
from app.rate_limit import limiter
from app.routers._deps import spotify_client
from app.routers.auth import get_current_user_id, validate_csrf_token
from app.schemas.podcast import (
    PodcastListResponse,
    PodcastResponse,
    PodcastUpdate,
)
from app.services.library_sync import UNSUBSCRIBE_GRACE, sync_library

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/podcasts", tags=["Podcasts"])

# How long a manual sync waits for library_sync_lock before giving up. The
# daily job can hold it for the length of a full /me/shows walk, and the
# client times out long before that — so fail fast with a 409 the UI can
# explain, matching the playlist write lock's treatment (issue #153).
SYNC_LOCK_WAIT_SECONDS = 5


async def _get_playlist_ids_for_podcast(db: AsyncSession, podcast_id: int) -> list[int]:
    """Get all playlist IDs that a podcast is assigned to."""
    result = await db.execute(select(PlaylistPodcast.playlist_id).where(PlaylistPodcast.podcast_id == podcast_id))
    return [row[0] for row in result.all()]


async def _get_podcast_or_404(db: AsyncSession, podcast_ref: str) -> Podcast:
    """Resolve a ``/podcasts/{podcast_id}`` path segment to a podcast.

    The canonical key is the integer ``id``, matching the assignment routes
    (``/playlists/{id}/podcasts/{podcast_id}``) — issue #248. A non-numeric
    segment is looked up as a Spotify show ID instead, so iOS builds from
    before the switch keep working; Spotify IDs are 22-character base62 and
    never all digits in practice. Drop the fallback once those builds are gone.
    """
    if podcast_ref.isdigit():
        result = await db.execute(select(Podcast).where(Podcast.id == int(podcast_ref)))
    else:
        result = await db.execute(select(Podcast).where(Podcast.spotify_id == podcast_ref))
    podcast = result.scalar_one_or_none()
    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")
    return podcast


def _build_podcast_response(podcast: Podcast, playlist_ids: list[int]) -> PodcastResponse:
    """Build a PodcastResponse with playlist_ids."""
    return PodcastResponse(
        id=podcast.id,
        spotify_id=podcast.spotify_id,
        name=podcast.name,
        description=podcast.description,
        image_url=podcast.image_url,
        publisher=podcast.publisher,
        total_episodes=podcast.total_episodes,
        unplayed_episodes=podcast.unplayed_episodes,
        unplayed_counted_at=podcast.unplayed_counted_at,
        is_sequential=podcast.is_sequential,
        is_archived=podcast.is_archived,
        playlist_ids=playlist_ids,
        last_synced_at=podcast.last_synced_at,
        missing_since=podcast.missing_since,
        created_at=podcast.created_at,
        updated_at=podcast.updated_at,
    )


@router.get("", response_model=PodcastListResponse)
async def list_podcasts(
    include_archived: bool = Query(False, description="Also return archived podcasts"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PodcastListResponse:
    """List all podcasts, paginated by name.

    Podcasts are a global table, not a per-user one — see the single-user
    note in ``CLAUDE.md`` (issue #154). Authentication is still required
    (``get_current_user_id``); there is simply no per-user partition to
    enforce, because registration closes after the first user.

    Archived podcasts are left out unless ``include_archived`` is set, so the
    dashboard counts and the assignment selects never see them (issue #247).

    There are no membership filters: both clients page through the whole
    library and filter locally, and ``GET /playlists/{id}/podcasts`` already
    covers "the shows in this playlist". The unused ``playlist_id`` /
    ``unassigned`` params were removed (issue #248).
    """
    query = select(Podcast)
    if not include_archived:
        query = query.where(Podcast.is_archived.is_(False))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    query = query.order_by(Podcast.name).offset(offset).limit(limit)
    result = await db.execute(query)
    podcasts = result.scalars().all()

    # Load all playlist IDs for these podcasts in a single query
    podcast_ids = [p.id for p in podcasts]
    playlist_ids_map: dict[int, list[int]] = {pid: [] for pid in podcast_ids}
    if podcast_ids:
        pp_result = await db.execute(
            select(PlaylistPodcast.podcast_id, PlaylistPodcast.playlist_id).where(
                PlaylistPodcast.podcast_id.in_(podcast_ids)
            )
        )
        for podcast_id, playlist_id in pp_result.all():
            playlist_ids_map[podcast_id].append(playlist_id)

    # Build responses with playlist_ids
    items = []
    for podcast in podcasts:
        pids = playlist_ids_map.get(podcast.id, [])
        items.append(_build_podcast_response(podcast, pids))

    return PodcastListResponse(items=items, total=total)


@router.get("/{podcast_id}", response_model=PodcastResponse)
async def get_podcast(
    podcast_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PodcastResponse:
    """Get a single podcast by ID."""
    podcast = await _get_podcast_or_404(db, podcast_id)

    pids = await _get_playlist_ids_for_podcast(db, podcast.id)
    return _build_podcast_response(podcast, pids)


@router.patch("/{podcast_id}", response_model=PodcastResponse)
async def update_podcast(
    podcast_id: str,
    update_data: PodcastUpdate,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> PodcastResponse:
    """Update podcast metadata.

    Archiving hides a podcast from the app while leaving it followed on
    Spotify. It also removes the podcast from every playlist: an archived show
    is invisible in the UI, so letting it keep contributing episodes would be
    a rule nobody can see (issue #247).
    """
    podcast = await _get_podcast_or_404(db, podcast_id)

    if update_data.is_sequential is not None:
        podcast.is_sequential = update_data.is_sequential
    if update_data.is_archived is not None:
        podcast.is_archived = update_data.is_archived
        if update_data.is_archived:
            await db.execute(delete(PlaylistPodcast).where(PlaylistPodcast.podcast_id == podcast.id))

    podcast.updated_at = datetime.now(UTC)

    await db.commit()  # persist before the response is sent (see get_db)

    pids = await _get_playlist_ids_for_podcast(db, podcast.id)
    return _build_podcast_response(podcast, pids)


@router.delete("/{podcast_id}")
async def unfollow_podcast(
    podcast_id: str,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Unfollow a podcast from Spotify and optionally remove from local database."""
    podcast = await _get_podcast_or_404(db, podcast_id)

    # Unfollow from Spotify
    spotify, token_manager = await spotify_client(db, session.user_id)
    try:
        await spotify.unfollow_show(podcast.spotify_id, on_unauthorized=token_manager.force_refresh)
    except httpx.HTTPError as e:
        logger.exception(f"Failed to unfollow podcast {podcast.spotify_id} on Spotify: {e}")
        raise HTTPException(
            status_code=502,
            detail="Could not unfollow the podcast on Spotify. Please try again.",
        ) from None

    # Remove from local database (cascade will remove join table entries)
    await db.delete(podcast)
    await db.commit()  # persist before the response is sent (see get_db)

    return {"message": f"Successfully unfollowed '{podcast.name}'"}


@router.post("/sync")
@limiter.limit("1/5minutes")
async def sync_podcasts(
    request: Request,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sync subscribed podcasts from Spotify.

    The walk and the subscription reconcile live in
    :func:`app.services.library_sync.sync_library`, shared with the daily job
    so a manual sync and an automatic one do exactly the same thing
    (issue #240).

    Serialised against the daily job's sync through ``library_sync_lock``:
    two concurrent walks can both insert a newly-followed show and the
    loser's commit dies on the ``spotify_id`` unique constraint. The lock is
    held across the commit — that is what makes the insert visible to the
    other walk — and a sync already in flight is rejected rather than queued,
    because the second walk would do the same work twice.
    """
    spotify, token_manager = await spotify_client(db, session.user_id)

    try:
        await asyncio.wait_for(locks.library_sync_lock.acquire(), timeout=SYNC_LOCK_WAIT_SECONDS)
    except TimeoutError:
        logger.info("Manual sync rejected — library_sync_lock held by another sync")
        raise HTTPException(
            status_code=409,
            detail="A library sync is already running. Please try again shortly.",
        ) from None

    try:
        result = await sync_library(db, spotify, on_unauthorized=token_manager.force_refresh)
        await db.commit()  # persist before the response is sent (see get_db)
    except httpx.HTTPError as e:
        # A partial walk reconciles nothing; get_db rolls the upserts back.
        logger.warning(f"Library sync failed talking to Spotify: {e}")
        raise HTTPException(
            status_code=502,
            detail="Could not load your podcasts from Spotify. Please try again.",
        ) from None
    finally:
        locks.library_sync_lock.release()

    message = "Sync completed"
    if result.removed:
        message += f", removed {result.removed} unsubscribed"
    if result.missing:
        message += f", {result.missing} no longer subscribed (removed after {UNSUBSCRIBE_GRACE.days} days)"

    return {
        "message": message,
        "synced": result.synced,
        "new": result.new,
        "missing": result.missing,
        "removed": result.removed,
        # True when the walk didn't look like a snapshot, so nothing was
        # marked or retired (see _reconcile_subscriptions). The upserts still
        # happened, so this isn't an error — but it isn't a complete sync
        # either, and the client shouldn't render it as one.
        "reconcile_skipped": not result.reconciled,
    }
