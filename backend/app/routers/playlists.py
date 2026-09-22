"""Playlists router for managing playlist configurations."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jobs import locks
from app.models.playlist import Playlist
from app.models.playlist_podcast import PlaylistPodcast
from app.models.podcast import Podcast
from app.models.session import Session
from app.models.user import User
from app.rate_limit import limiter
from app.routers.auth import get_current_user_id, validate_csrf_token
from app.schemas.playlist import (
    AssignmentOverride,
    AssignmentOverrideUpdate,
    AssignmentRule,
    PlaylistCreate,
    PlaylistListResponse,
    PlaylistPodcastAdd,
    PlaylistPodcastListResponse,
    PlaylistPodcastReorder,
    PlaylistPodcastResponse,
    PlaylistResponse,
    PlaylistUpdate,
)
from app.services.assignment_rules import resolve_rule
from app.services.playlist_builder import PlaylistBuilder, spotify_playlist_description
from app.services.spotify import SpotifyService
from app.services.token_manager import TokenManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/playlists", tags=["Playlists"])

# How long a manual run will wait for the shared write lock before giving up.
# A scheduled rebuild can hold it for many minutes, and nginx cuts the request
# off at 30s anyway — so fail fast with a 409 the UI can explain, rather than
# blocking until the client times out (issue #153).
WRITE_LOCK_WAIT_SECONDS = 5

# Refusal for a manual run of a disabled playlist (issue #239). Checked twice:
# once up front, and again once the write lock is held.
DISABLED_PLAYLIST_DETAIL = "This playlist is disabled. Enable it to run it."


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


def _is_not_found(exc: Exception) -> bool:
    """True for a Spotify 404 — the playlist is already gone on Spotify."""
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404


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
        is_enabled=playlist.is_enabled,
        is_weekend_only=playlist.is_weekend_only,
        default_episode_limit=playlist.default_episode_limit,
        default_pick_from=playlist.default_pick_from,
        arrangement=playlist.arrangement,
        date_direction=playlist.date_direction,
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
        is_enabled=playlist_data.is_enabled,
        is_weekend_only=playlist_data.is_weekend_only,
        default_episode_limit=playlist_data.default_episode_limit,
        default_pick_from=playlist_data.default_pick_from.value,
        arrangement=playlist_data.arrangement.value,
        date_direction=playlist_data.date_direction.value,
    )
    db.add(playlist)
    await db.commit()  # persist before the response is sent (see get_db)

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

    if update_data.spotify_playlist_id is not None:
        playlist.spotify_playlist_id = update_data.spotify_playlist_id
    if update_data.name is not None and update_data.name != playlist.name:
        # The name is otherwise only used when the Spotify playlist is first
        # created, so push a rename through (issue #247). Spotify first: if it
        # fails nothing is saved and the user can retry, rather than the two
        # names silently drifting apart. A 404 means the Spotify playlist is
        # gone — there is nothing to rename, so the local rename goes ahead.
        if playlist.spotify_playlist_id:
            token_manager = TokenManager(session.user_id)
            try:
                spotify = SpotifyService(access_token=await token_manager.get_token())
                await spotify.update_playlist_details(
                    playlist.spotify_playlist_id,
                    name=update_data.name,
                    description=spotify_playlist_description(update_data.name),
                    on_unauthorized=token_manager.force_refresh,
                )
            except Exception as e:
                if not _is_not_found(e):
                    logger.exception(f"Failed to rename Spotify playlist {playlist.spotify_playlist_id}: {e}")
                    raise HTTPException(
                        status_code=502,
                        detail="Could not rename the playlist on Spotify, so nothing was saved. Please try again.",
                    ) from None
                logger.info(f"Spotify playlist {playlist.spotify_playlist_id} not found; renaming locally only")
        playlist.name = update_data.name
    if update_data.is_enabled is not None:
        playlist.is_enabled = update_data.is_enabled
    if update_data.is_weekend_only is not None:
        playlist.is_weekend_only = update_data.is_weekend_only
    if update_data.default_episode_limit is not None:
        playlist.default_episode_limit = update_data.default_episode_limit
    if update_data.default_pick_from is not None:
        playlist.default_pick_from = update_data.default_pick_from.value
    if update_data.arrangement is not None:
        playlist.arrangement = update_data.arrangement.value
    if update_data.date_direction is not None:
        playlist.date_direction = update_data.date_direction.value

    await db.commit()  # persist before the response is sent (see get_db)

    count = await _get_podcast_count(db, playlist.id)
    return _build_playlist_response(playlist, count)


@router.delete("/{playlist_id}")
async def delete_playlist(
    playlist_id: int,
    remove_from_spotify: bool = Query(False, description="Also delete (unfollow) the playlist on Spotify"),
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a playlist mapping, optionally removing the Spotify playlist too.

    Without ``remove_from_spotify`` the Spotify playlist is left in place (and
    no longer updated). With it, the playlist is unfollowed on Spotify first —
    that is how Spotify deletes a playlist you own — and only then removed
    locally, so a Spotify failure leaves everything as it was (issue #247).
    """
    result = await db.execute(
        select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == session.user_id))
    )
    playlist = result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    if remove_from_spotify and playlist.spotify_playlist_id:
        # Hold the write lock so a rebuild can't be writing to the playlist
        # (or, for a new one, creating it) while it is removed.
        async with _playlist_write_lock():
            token_manager = TokenManager(session.user_id)
            try:
                spotify = SpotifyService(access_token=await token_manager.get_token())
                await spotify.unfollow_playlist(
                    playlist.spotify_playlist_id,
                    on_unauthorized=token_manager.force_refresh,
                )
            except Exception as e:
                # Already gone on Spotify is the outcome we wanted.
                if not _is_not_found(e):
                    logger.exception(f"Failed to remove Spotify playlist {playlist.spotify_playlist_id}: {e}")
                    raise HTTPException(
                        status_code=502,
                        detail="Could not remove the playlist from Spotify, so it was not deleted. Please try again.",
                    ) from None

            await db.delete(playlist)
            await db.commit()  # persist before the response is sent (see get_db)
        return {"message": "Playlist deleted from the app and Spotify"}

    await db.delete(playlist)
    await db.commit()  # persist before the response is sent (see get_db)
    return {"message": "Playlist deleted"}


# --- Playlist-Podcast assignment endpoints ---


def _build_assignment_response(
    playlist: Playlist, podcast: Podcast, assignment: PlaylistPodcast
) -> PlaylistPodcastResponse:
    """Build one assignment row with its resolved rule and raw override."""
    rule = resolve_rule(playlist, podcast, assignment)
    return PlaylistPodcastResponse(
        id=podcast.id,
        spotify_id=podcast.spotify_id,
        name=podcast.name,
        description=podcast.description,
        image_url=podcast.image_url,
        publisher=podcast.publisher,
        total_episodes=podcast.total_episodes,
        unplayed_episodes=podcast.unplayed_episodes,
        is_sequential=podcast.is_sequential,
        position=assignment.position,
        rule=AssignmentRule(
            episode_limit=rule.episode_limit,
            pick_from=rule.pick_from,
            episode_limit_source=rule.episode_limit_source,
            pick_from_source=rule.pick_from_source,
        ),
        override=AssignmentOverride(
            episode_limit=assignment.episode_limit,
            pick_from=assignment.pick_from,
        ),
    )


async def _get_owned_playlist(db: AsyncSession, playlist_id: int, user_id: int) -> Playlist:
    """Load a playlist scoped to the user, or 404."""
    result = await db.execute(select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == user_id)))
    playlist = result.scalar_one_or_none()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist


@router.get("/{playlist_id}/podcasts", response_model=PlaylistPodcastListResponse)
async def list_playlist_podcasts(
    playlist_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PlaylistPodcastListResponse:
    """List podcasts assigned to a playlist, ordered by position.

    Each row carries the rule the next build will apply (resolved through
    ``resolve_rule``) and the raw override, so the UI can show which parts
    are inherited and offer "reset to default".
    """
    playlist = await _get_owned_playlist(db, playlist_id, user_id)

    result = await db.execute(
        select(Podcast, PlaylistPodcast)
        .join(PlaylistPodcast, PlaylistPodcast.podcast_id == Podcast.id)
        .where(PlaylistPodcast.playlist_id == playlist_id)
        .order_by(
            PlaylistPodcast.position.is_(None),
            PlaylistPodcast.position,
            Podcast.name,
        )
    )
    rows = result.all()

    items = [_build_assignment_response(playlist, podcast, assignment) for podcast, assignment in rows]
    return PlaylistPodcastListResponse(items=items, total=len(items))


@router.patch("/{playlist_id}/podcasts/{podcast_id}", response_model=PlaylistPodcastResponse)
async def update_playlist_podcast(
    playlist_id: int,
    podcast_id: int,
    data: AssignmentOverrideUpdate,
    session: Session = Depends(validate_csrf_token),
    db: AsyncSession = Depends(get_db),
) -> PlaylistPodcastResponse:
    """Set or clear the per-assignment overrides.

    A field present in the body and ``null`` clears that override (the row
    goes back to inheriting); an absent field is left alone.
    """
    playlist = await _get_owned_playlist(db, playlist_id, session.user_id)

    result = await db.execute(
        select(Podcast, PlaylistPodcast)
        .join(PlaylistPodcast, PlaylistPodcast.podcast_id == Podcast.id)
        .where((PlaylistPodcast.playlist_id == playlist_id) & (PlaylistPodcast.podcast_id == podcast_id))
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Podcast not assigned to this playlist")
    podcast, assignment = row

    if "episode_limit" in data.model_fields_set:
        assignment.episode_limit = data.episode_limit
    if "pick_from" in data.model_fields_set:
        assignment.pick_from = data.pick_from.value if data.pick_from is not None else None

    await db.commit()  # persist before the response is sent (see get_db)

    return _build_assignment_response(playlist, podcast, assignment)


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
    # Dedupe while preserving order — with autoflush off, a repeated ID in one
    # request passes the existence check twice (the second SELECT can't see the
    # first pending add) and 500s on the unique constraint (issue #182).
    for podcast_id in dict.fromkeys(data.podcast_ids):
        # Verify podcast exists
        # Archived podcasts are hidden from the app, so they can't be assigned
        # (issue #247) — skip them like an unknown ID.
        podcast_result = await db.execute(
            select(Podcast).where((Podcast.id == podcast_id) & (Podcast.is_archived.is_(False)))
        )
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

    await db.commit()  # persist before the response is sent (see get_db)

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
    await db.commit()  # persist before the response is sent (see get_db)

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

    await db.commit()  # persist before the response is sent (see get_db)

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
    """Manually trigger a playlist update.

    Disabled playlists are refused with a 409 — see the ``is_enabled`` gates
    below (issue #239): once up front, and again under the write lock.

    ``/run-all`` needs no such re-read: ``update_all_playlists`` runs its
    ``is_enabled`` query inside the lock, as the daily job does.
    """
    # Get the playlist
    playlist_result = await db.execute(
        select(Playlist).where((Playlist.id == playlist_id) & (Playlist.user_id == session.user_id))
    )
    playlist = playlist_result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Disabled means "never written to on Spotify" — by the daily rebuild, by
    # the cleanup job, and by a manual run too (issue #239). Refuse here
    # rather than silently skipping, so a client that offers the button at
    # all gets told why nothing happened.
    if not playlist.is_enabled:
        raise HTTPException(status_code=409, detail=DISABLED_PLAYLIST_DETAIL)

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
        # The check above ran before the wait, and PATCH /playlists/{id}
        # doesn't take this lock — so re-read the row now. A playlist
        # disabled while this request queued behind the daily rebuild must
        # not be written either (issue #239).
        await db.refresh(playlist)
        if not playlist.is_enabled:
            raise HTTPException(status_code=409, detail=DISABLED_PLAYLIST_DETAIL)

        builder = PlaylistBuilder(db, user, token_manager=TokenManager(user.id))
        result = await builder.update_playlist(playlist)

    # Persist the builder's flushed writes (last_updated_at) before the
    # response is sent (see get_db). No-op on the failure path.
    await db.commit()

    if not result.success and not result.partial:
        # Log the detail; don't hand raw exception text to the client (issue #161).
        logger.error(f"Manual run failed for playlist '{playlist.name}': {result.error}")
        raise HTTPException(status_code=500, detail="Failed to update playlist. Check the server logs for details.")

    if result.skipped:
        # Weekend-only playlist on a non-qualifying day — deliberately left
        # untouched, so say so rather than claiming an update (issue #150).
        return {
            "message": f"Playlist '{playlist.name}' is weekend-only and was left unchanged today",
            "playlist_id": playlist_id,
            "episode_count": 0,
            "skipped": True,
        }

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

    # Persist the builder's flushed writes (last_updated_at) before the
    # response is sent (see get_db).
    await db.commit()

    skipped = [r for r in results if r.skipped]
    partial = [r for r in results if r.partial]
    successful = [r for r in results if r.success and not r.skipped]
    failed = [r for r in results if not r.success and not r.partial]

    # Log the detail; don't hand raw exception text to the client (issue #161).
    # Partial results keep their message — it names the podcasts we couldn't
    # reach, which is ours, not an arbitrary exception string.
    for r in failed:
        logger.error(f"Manual run-all failed for playlist '{r.playlist_name}': {r.error}")

    message = f"Updated {len(successful)} playlists, {len(failed)} failed"
    if partial:
        message += f", {len(partial)} updated with warnings"
    if skipped:
        message += f", {len(skipped)} skipped (weekend-only)"

    return {
        "message": message,
        "results": [
            {
                "playlist_id": r.playlist_id,
                "playlist_name": r.playlist_name,
                "success": r.success,
                "episode_count": r.episode_count,
                "error": r.error
                if r.partial
                else ("Failed to update playlist. Check the server logs for details." if r.error else None),
                "partial": r.partial,
                "skipped": r.skipped,
            }
            for r in results
        ],
    }
