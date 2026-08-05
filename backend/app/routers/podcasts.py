"""Podcasts router for managing podcast metadata."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.playlist import Playlist
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
    playlist_id: int | None = Query(None, description="Filter by playlist membership"),
    unassigned: bool = Query(False, description="Only return podcasts not assigned to any playlist"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PodcastListResponse:
    """List all podcasts with optional filters."""
    query = select(Podcast)

    if playlist_id is not None:
        # Verify the playlist belongs to the caller before filtering through it.
        # Today the single-user guard in auth.py makes this a no-op, but this
        # closes a latent IDOR if multi-user is ever enabled.
        owner_check = await db.execute(
            select(Playlist.id).where((Playlist.id == playlist_id) & (Playlist.user_id == user_id))
        )
        if owner_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Playlist not found")

        # Filter to podcasts in this playlist
        query = query.join(PlaylistPodcast, PlaylistPodcast.podcast_id == Podcast.id).where(
            PlaylistPodcast.playlist_id == playlist_id
        )
    elif unassigned:
        # Filter to podcasts NOT in any playlist
        assigned_subquery = select(PlaylistPodcast.podcast_id).distinct()
        query = query.where(Podcast.id.not_in(assigned_subquery))

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


@router.get("/{spotify_id}", response_model=PodcastResponse)
async def get_podcast(
    spotify_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PodcastResponse:
    """Get a single podcast by Spotify ID."""
    result = await db.execute(select(Podcast).where(Podcast.spotify_id == spotify_id))
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    pids = await _get_playlist_ids_for_podcast(db, podcast.id)
    return _build_podcast_response(podcast, pids)


@router.patch("/{spotify_id}", response_model=PodcastResponse)
async def update_podcast(
    spotify_id: str,
    update_data: PodcastUpdate,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> PodcastResponse:
    """Update podcast metadata."""
    result = await db.execute(select(Podcast).where(Podcast.spotify_id == spotify_id))
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    if update_data.is_sequential is not None:
        podcast.is_sequential = update_data.is_sequential

    podcast.updated_at = datetime.now(UTC)

    await db.flush()

    pids = await _get_playlist_ids_for_podcast(db, podcast.id)
    return _build_podcast_response(podcast, pids)


@router.delete("/{spotify_id}")
async def unfollow_podcast(
    spotify_id: str,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Unfollow a podcast from Spotify and optionally remove from local database."""
    user, access_token = await get_user_with_token(session.user_id, db)

    # Check if podcast exists in our database
    result = await db.execute(select(Podcast).where(Podcast.spotify_id == spotify_id))
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    # Unfollow from Spotify
    spotify = SpotifyService(access_token=access_token)
    try:
        await spotify.unfollow_show(spotify_id)
    except Exception as e:
        logger.exception(f"Failed to unfollow podcast {spotify_id} on Spotify: {e}")
        raise HTTPException(status_code=500, detail="Failed to unfollow podcast on Spotify") from None

    # Remove from local database (cascade will remove join table entries)
    await db.delete(podcast)
    await db.flush()

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

    while True:
        # Fetch shows from Spotify
        shows_data = await spotify.get_user_shows(limit=limit, offset=offset)
        items = shows_data.get("items", [])

        if not items:
            break

        for item in items:
            show = item.get("show", {})
            spotify_id = show.get("id")

            if not spotify_id:
                continue

            # Check if podcast exists
            result = await db.execute(select(Podcast).where(Podcast.spotify_id == spotify_id))
            podcast = result.scalar_one_or_none()

            # Get image URL (prefer medium size)
            images = show.get("images", [])
            image_url = images[0]["url"] if images else None

            # Count unplayed episodes by fetching episodes with resume_point
            unplayed_count = 0
            try:
                episodes_data = await spotify.get_show_episodes(spotify_id, limit=50)
                episodes = episodes_data.get("items", [])

                for episode in episodes:
                    resume_point = episode.get("resume_point", {})
                    fully_played = resume_point.get("fully_played", False)
                    if not fully_played:
                        unplayed_count += 1

                # If there are more than 50 episodes, approximate based on first 50
                total_eps = show.get("total_episodes", 0)
                if total_eps > 50 and len(episodes) > 0:
                    unplayed_ratio = unplayed_count / len(episodes)
                    unplayed_count = int(total_eps * unplayed_ratio)
            except Exception as e:
                # If we can't fetch episodes, keep previous count or 0
                logger.warning(f"Failed to fetch episodes for {spotify_id}: {e}")
                unplayed_count = podcast.unplayed_episodes if podcast else 0

            if podcast:
                # Update existing podcast
                podcast.name = show.get("name", podcast.name)
                podcast.description = show.get("description")
                podcast.image_url = image_url
                podcast.publisher = show.get("publisher")
                podcast.total_episodes = show.get("total_episodes", 0)
                podcast.unplayed_episodes = unplayed_count
                podcast.last_synced_at = datetime.now(UTC)
            else:
                # Create new podcast
                podcast = Podcast(
                    spotify_id=spotify_id,
                    name=show.get("name", "Unknown"),
                    description=show.get("description"),
                    image_url=image_url,
                    publisher=show.get("publisher"),
                    total_episodes=show.get("total_episodes", 0),
                    unplayed_episodes=unplayed_count,
                    last_synced_at=datetime.now(UTC),
                )
                db.add(podcast)
                new_count += 1

            synced_count += 1

        offset += limit

        # Check if there are more pages
        if len(items) < limit:
            break

    await db.flush()

    return {
        "message": "Sync completed",
        "synced": synced_count,
        "new": new_count,
    }
