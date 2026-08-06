"""Playlists router for managing playlist configurations."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jobs import locks
from app.models.playlist import Playlist, PlaylistOrderingMode
from app.models.playlist_podcast import PlaylistPodcast
from app.models.podcast import Podcast
from app.models.session import Session
from app.models.user import User
from app.rate_limit import limiter
from app.routers.auth import get_current_user_id, validate_csrf_token
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistListResponse,
    PlaylistPodcastAdd,
    PlaylistPodcastListResponse,
    PlaylistPodcastReorder,
    PlaylistPodcastResponse,
    PlaylistResponse,
    PlaylistUpdate,
)
from app.services.playlist_builder import PlaylistBuilder
from app.services.token_manager import TokenManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/playlists", tags=["Playlists"])

# How long a manual run will wait for the shared write lock before giving up.
# A scheduled rebuild can hold it for many minutes, and nginx cuts the request
# off at 30s anyway — so fail fast with a 409 the UI can explain, rather than
# blocking until the client times out (issue #153).
WRITE_LOCK_WAIT_SECONDS = 5


@asynccontextmanager
async def _playlist_write_lock() -> AsyncIterator[None]:
    """Acquire the shared playlist write lock or raise 409.

    Serialises manual runs against the daily rebuild and the cleanup job
    (issue #89, PR3) without leaving the caller hanging (issue #153).
    """
    try:
        await asyncio.wait_for(locks.playlist_write_lock.acquire(), timeout=WRITE_LOCK_WAIT_SECONDS)
    except TimeoutError:
        logger.info("Manual run rejected — playlist_write_lock held by another job")
        raise HTTPException(
            status_code=409,
            detail="A playlist update is already running. Please try again shortly.",
        ) from None

    try:
        yield
    finally:
        locks.playlist_write_lock.release()


async def _get_podcast_count(db: AsyncSession, playlist_id: int) -> int:
    """Get the number of podcasts assigned to a playlist."""
    result = await db.execute(
        select(func.count()).select_from(PlaylistPodcast).where(PlaylistPodcast.playlist_id == playlist_id)
    )
    return result.scalar() or 0


def _build_playlist_response(playlist: Playlist, podcast_count: int) -> PlaylistResponse:
    """Build a PlaylistResponse with podcast_count."""
    return PlaylistResponse(
        id=playlist.id,
        name=playlist.name,
        episode_mode=playlist.episode_mode,
        is_enabled=playlist.is_enabled,
        is_weekend_only=playlist.is_weekend_only,
        ordering_mode=playlist.ordering_mode,
        spotify_playlist_id=playlist.spotify_playlist_id,
        last_updated_at=playlist.last_updated_at,
        created_at=playlist.created_at,
        podcast_count=podcast_count,
    )


@router.get("", response_model=PlaylistListResponse)
async def list_playlists(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PlaylistListResponse:
    """List all managed playlists."""
    result = await db.execute(select(Playlist).where(Playlist.user_id == user_id).order_by(Playlist.name))
    playlists = result.scalars().all()

    # Load all podcast counts in a single query instead of N+1
    playlist_ids = [p.id for p in playlists]
    counts_map: dict[int, int] = {pid: 0 for pid in playlist_ids}
    if playlist_ids:
        counts_result = await db.execute(
            select(PlaylistPodcast.playlist_id, func.count())
            .where(PlaylistPodcast.playlist_id.in_(playlist_ids))
            .group_by(PlaylistPodcast.playlist_id)
        )
        for playlist_id, count in counts_result.all():
            counts_map[playlist_id] = count

    items = []
    for playlist in playlists:
        count = counts_map.get(playlist.id, 0)
        items.append(_build_playlist_response(playlist, count))

    return PlaylistListResponse(items=items, total=len(items))


@router.post("", response_model=PlaylistResponse, status_code=201)
async def create_playlist(
    playlist_data: PlaylistCreate,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> PlaylistResponse:
    """Create a new playlist."""
    playlist = Playlist(
        user_id=session.user_id,
        name=playlist_data.name,
        spotify_playlist_id=playlist_data.spotify_playlist_id,
        episode_mode=playlist_data.episode_mode.value,
        is_enabled=playlist_data.is_enabled,
        is_weekend_only=playlist_data.is_weekend_only,
        ordering_mode=PlaylistOrderingMode(playlist_data.ordering_mode.value)
        if playlist_data.ordering_mode
        else PlaylistOrderingMode.DEFAULT,
    )
    db.add(playlist)
    await db.flush()

    return _build_playlist_response(playlist, 0)


@router.get("/{playlist_id}", response_model=PlaylistResponse)
async def get_playlist(
    playlist_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PlaylistResponse:
    """Get a playlist by ID."""
    result = await db.execute(select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == user_id)))
    playlist = result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    count = await _get_podcast_count(db, playlist.id)
    return _build_playlist_response(playlist, count)


@router.patch("/{playlist_id}", response_model=PlaylistResponse)
async def update_playlist(
    playlist_id: int,
    update_data: PlaylistUpdate,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> PlaylistResponse:
    """Update playlist configuration."""
    result = await db.execute(
        select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == session.user_id))
    )
    playlist = result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    if update_data.name is not None:
        playlist.name = update_data.name
    if update_data.spotify_playlist_id is not None:
        playlist.spotify_playlist_id = update_data.spotify_playlist_id
    if update_data.is_enabled is not None:
        playlist.is_enabled = update_data.is_enabled
    if update_data.episode_mode is not None:
        playlist.episode_mode = update_data.episode_mode.value
    if update_data.is_weekend_only is not None:
        playlist.is_weekend_only = update_data.is_weekend_only
    if update_data.ordering_mode is not None:
        playlist.ordering_mode = PlaylistOrderingMode(update_data.ordering_mode.value)

    await db.flush()

    count = await _get_podcast_count(db, playlist.id)
    return _build_playlist_response(playlist, count)


@router.delete("/{playlist_id}")
async def delete_playlist(
    playlist_id: int,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a playlist mapping."""
    result = await db.execute(
        select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == session.user_id))
    )
    playlist = result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    await db.delete(playlist)
    return {"message": "Playlist deleted"}


# --- Playlist-Podcast assignment endpoints ---


@router.get("/{playlist_id}/podcasts", response_model=PlaylistPodcastListResponse)
async def list_playlist_podcasts(
    playlist_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """List podcasts assigned to a playlist, ordered by position."""
    # Verify playlist exists and belongs to user
    playlist_result = await db.execute(
        select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == user_id))
    )
    if not playlist_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Playlist not found")

    result = await db.execute(
        select(Podcast, PlaylistPodcast.position)
        .join(PlaylistPodcast, PlaylistPodcast.podcast_id == Podcast.id)
        .where(PlaylistPodcast.playlist_id == playlist_id)
        .order_by(
            PlaylistPodcast.position.is_(None),
            PlaylistPodcast.position,
            Podcast.name,
        )
    )
    rows = result.all()

    items = [
        PlaylistPodcastResponse(
            id=podcast.id,
            spotify_id=podcast.spotify_id,
            name=podcast.name,
            description=podcast.description,
            image_url=podcast.image_url,
            publisher=podcast.publisher,
            total_episodes=podcast.total_episodes,
            unplayed_episodes=podcast.unplayed_episodes,
            is_sequential=podcast.is_sequential,
            position=position,
        )
        for podcast, position in rows
    ]
    return {"items": items, "total": len(items)}


@router.post("/{playlist_id}/podcasts")
async def add_podcasts_to_playlist(
    playlist_id: int,
    data: PlaylistPodcastAdd,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add podcasts to a playlist."""
    # Verify playlist exists and belongs to user
    playlist_result = await db.execute(
        select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == session.user_id))
    )
    if not playlist_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Get current max position
    max_pos_result = await db.execute(
        select(func.max(PlaylistPodcast.position)).where(PlaylistPodcast.playlist_id == playlist_id)
    )
    max_position = max_pos_result.scalar() or 0

    added = 0
    for podcast_id in data.podcast_ids:
        # Verify podcast exists
        podcast_result = await db.execute(select(Podcast).where(Podcast.id == podcast_id))
        if not podcast_result.scalar_one_or_none():
            continue

        # Check if already assigned
        existing = await db.execute(
            select(PlaylistPodcast).where(
                (PlaylistPodcast.playlist_id == playlist_id) & (PlaylistPodcast.podcast_id == podcast_id)
            )
        )
        if existing.scalar_one_or_none():
            continue

        max_position += 1
        assignment = PlaylistPodcast(
            playlist_id=playlist_id,
            podcast_id=podcast_id,
            position=max_position,
        )
        db.add(assignment)
        added += 1

    await db.flush()

    return {"message": f"Added {added} podcast(s) to playlist", "added": added}


@router.delete("/{playlist_id}/podcasts/{podcast_id}")
async def remove_podcast_from_playlist(
    playlist_id: int,
    podcast_id: int,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Remove a podcast from a playlist."""
    # Verify playlist belongs to user
    playlist_result = await db.execute(
        select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == session.user_id))
    )
    if not playlist_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Playlist not found")

    result = await db.execute(
        select(PlaylistPodcast).where(
            (PlaylistPodcast.playlist_id == playlist_id) & (PlaylistPodcast.podcast_id == podcast_id)
        )
    )
    assignment = result.scalar_one_or_none()

    if not assignment:
        raise HTTPException(status_code=404, detail="Podcast not assigned to this playlist")

    await db.delete(assignment)
    await db.flush()

    return {"message": "Podcast removed from playlist"}


@router.put("/{playlist_id}/podcasts/reorder")
async def reorder_playlist_podcasts(
    playlist_id: int,
    data: PlaylistPodcastReorder,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Reorder podcasts within a playlist.

    The podcast_ids list defines the new order. Position is assigned
    based on the index in the list (1-based).
    """
    # Verify playlist belongs to user
    playlist_result = await db.execute(
        select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == session.user_id))
    )
    if not playlist_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Playlist not found")

    for position, podcast_id in enumerate(data.podcast_ids, start=1):
        result = await db.execute(
            select(PlaylistPodcast).where(
                (PlaylistPodcast.playlist_id == playlist_id) & (PlaylistPodcast.podcast_id == podcast_id)
            )
        )
        assignment = result.scalar_one_or_none()

        if not assignment:
            raise HTTPException(
                status_code=400,
                detail=f"Podcast {podcast_id} is not assigned to this playlist",
            )

        assignment.position = position

    await db.flush()

    return {"message": "Podcasts reordered"}


# --- Playlist run endpoints ---


@router.post("/{playlist_id}/run")
@limiter.limit("3/10minutes")
async def run_playlist_update(
    request: Request,
    playlist_id: int,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger a playlist update."""
    # Get the playlist
    playlist_result = await db.execute(
        select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == session.user_id))
    )
    playlist = playlist_result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Get the user
    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Build and update the playlist — use the same TokenManager-based
    # plumbing as the scheduled job so manual runs also get just-in-time
    # token refresh at the write boundary (issue #89, AC #5).
    # Take the shared write lock so a manual run serialises against
    # the daily rebuild and the cleanup job (issue #89, PR3, AC #3).
    async with _playlist_write_lock():
        builder = PlaylistBuilder(db, user, token_manager=TokenManager(user.id))
        result = await builder.update_playlist(playlist)

    if not result.success and not result.partial:
        # Log the detail; don't hand raw exception text to the client (issue #161).
        logger.error(f"Manual run failed for playlist '{playlist.name}': {result.error}")
        raise HTTPException(status_code=500, detail="Failed to update playlist. Check the server logs for details.")

    if result.partial:
        # The playlist was written, just from incomplete data — the message
        # names the podcasts we couldn't reach, which is ours, not an
        # arbitrary exception string.
        return {
            "message": f"Playlist '{playlist.name}' updated with warnings: {result.error}",
            "playlist_id": playlist_id,
            "episode_count": result.episode_count,
            "partial": True,
        }

    return {
        "message": f"Playlist '{playlist.name}' updated successfully",
        "playlist_id": playlist_id,
        "episode_count": result.episode_count,
    }


@router.post("/run-all")
@limiter.limit("1/5minutes")
async def run_all_playlist_updates(
    request: Request,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger all enabled playlist updates."""
    # Get the user
    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update all playlists — same plumbing as the scheduled job (issue #89).
    # Take the shared write lock so manual fan-out serialises against the
    # daily rebuild and the cleanup job (issue #89, PR3, AC #3).
    async with _playlist_write_lock():
        builder = PlaylistBuilder(db, user, token_manager=TokenManager(user.id))
        results = await builder.update_all_playlists()

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    return {
        "message": f"Updated {len(successful)} playlists, {len(failed)} failed",
        "results": [
            {
                "playlist_id": r.playlist_id,
                "playlist_name": r.playlist_name,
                "success": r.success,
                "episode_count": r.episode_count,
                "error": r.error,
            }
            for r in results
        ],
    }
