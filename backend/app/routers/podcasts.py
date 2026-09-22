"""Podcasts router for managing podcast metadata."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
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
        playlist_ids=playlist_ids,
        last_synced_at=podcast.last_synced_at,
        created_at=podcast.created_at,
        updated_at=podcast.updated_at,
    )


@router.get("", response_model=PodcastListResponse)
async def list_podcasts(
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

    There are no filters: both clients page through the whole library and
    filter locally, and ``GET /playlists/{id}/podcasts`` already covers "the
    shows in this playlist". The unused ``playlist_id`` / ``unassigned``
    params were removed (issue #248).
    """
    query = select(Podcast)

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
    """Update podcast metadata."""
    podcast = await _get_podcast_or_404(db, podcast_id)

    if update_data.is_sequential is not None:
        podcast.is_sequential = update_data.is_sequential

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
    """Sync subscribed podcasts from Spotify."""
    user, access_token = await get_user_with_token(session.user_id, db)

    spotify = SpotifyService(access_token=access_token)

    synced_count = 0
    new_count = 0
    offset = 0
    limit = 50
    # Spotify pagination can hand back the same show on two pages (the list
    # shifts under us mid-sync). With autoflush off, the existence SELECT
    # can't see the first pending insert, so a repeat would 500 the whole
    # sync on the unique constraint — skip anything already seen (issue #182).
    seen_spotify_ids: set[str] = set()

    while True:
        # Fetch shows from Spotify
        shows_data = await spotify.get_user_shows(limit=limit, offset=offset)
        items = shows_data.get("items", [])

        if not items:
            break

        for item in items:
            show = item.get("show", {})
            spotify_id = show.get("id")

            if not spotify_id or spotify_id in seen_spotify_ids:
                continue
            seen_spotify_ids.add(spotify_id)

            # Check if podcast exists
            result = await db.execute(select(Podcast).where(Podcast.spotify_id == spotify_id))
            podcast = result.scalar_one_or_none()

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
                new_count += 1

            synced_count += 1

        offset += limit

        # Check if there are more pages
        if len(items) < limit:
            break

    await db.commit()  # persist before the response is sent (see get_db)

    return {
        "message": "Sync completed",
        "synced": synced_count,
        "new": new_count,
    }
