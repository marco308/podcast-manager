"""Podcasts router for managing podcast metadata."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.playlist_podcast import PlaylistPodcast
from app.models.podcast import Podcast
from app.models.session import Session
from app.models.user import User
from app.rate_limit import limiter
from app.routers.auth import get_current_user_id, validate_csrf_token
from app.schemas.podcast import (
    PodcastListResponse,
    PodcastResponse,
    PodcastUpdate,
)
from app.services.encryption import TokenDecryptionError, get_encryption_service
from app.services.library_sync import sync_library
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/podcasts", tags=["Podcasts"])


async def get_user_with_token(
    user_id: int,
    db: AsyncSession,
) -> tuple[User, str]:
    """Get user and decrypted access token."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    encryption = get_encryption_service()
    try:
        access_token = encryption.decrypt(user.access_token)
    except TokenDecryptionError:
        # Stored ciphertext is unreadable (key rotation, corruption). Force reauth
        # instead of surfacing a 500 from the global handler.
        logger.warning(f"Access token for user {user.id} could not be decrypted; forcing reauth")
        raise HTTPException(
            status_code=401,
            detail="Stored credentials could not be read. Please sign in again.",
        ) from None

    return user, access_token


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
        is_sequential=podcast.is_sequential,
        is_archived=podcast.is_archived,
        playlist_ids=playlist_ids,
        last_synced_at=podcast.last_synced_at,
        unfollowed_at=podcast.unfollowed_at,
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
    user, access_token = await get_user_with_token(session.user_id, db)

    podcast = await _get_podcast_or_404(db, podcast_id)

    # Unfollow from Spotify
    spotify = SpotifyService(access_token=access_token)
    try:
        await spotify.unfollow_show(podcast.spotify_id)
    except Exception as e:
        logger.exception(f"Failed to unfollow podcast {podcast.spotify_id} on Spotify: {e}")
        raise HTTPException(status_code=500, detail="Failed to unfollow podcast on Spotify") from None

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

    The walk and the unfollow reconciliation live in
    :func:`app.services.library_sync.sync_library`, shared with the daily
    job so a manual sync and an automatic one do exactly the same thing
    (issue #240).
    """
    user, access_token = await get_user_with_token(session.user_id, db)

    spotify = SpotifyService(access_token=access_token)
    result = await sync_library(db, spotify)

    await db.commit()  # persist before the response is sent (see get_db)

    return {
        "message": "Sync completed",
        "synced": result.synced,
        "new": result.new,
        "unfollowed": result.unfollowed,
        "refollowed": result.refollowed,
    }
