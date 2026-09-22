"""Podcasts router for managing podcast metadata."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
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

# How long a podcast must stay absent from the Spotify library before sync
# deletes it (issue #155). Deleting cascades to playlist assignments, so one
# sync's word isn't enough: a single paginated walk is never a guaranteed
# snapshot of the library.
UNSUBSCRIBE_GRACE = timedelta(days=7)


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
        is_archived=podcast.is_archived,
        playlist_ids=playlist_ids,
        last_synced_at=podcast.last_synced_at,
        created_at=podcast.created_at,
        updated_at=podcast.updated_at,
    )


@router.get("", response_model=PodcastListResponse)
async def list_podcasts(
    playlist_id: int | None = Query(None, description="Filter by playlist membership"),
    unassigned: bool = Query(False, description="Only return podcasts not assigned to any playlist"),
    include_archived: bool = Query(False, description="Also return archived podcasts"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PodcastListResponse:
    """List all podcasts with optional filters.

    Podcasts are a global table, not a per-user one — see the single-user
    note in ``CLAUDE.md`` (issue #154). Authentication is still required
    (``get_current_user_id``); there is simply no per-user partition to
    enforce, because registration closes after the first user.

    Archived podcasts are left out unless ``include_archived`` is set, so the
    dashboard counts and the assignment selects never see them (issue #247).
    """
    query = select(Podcast)
    if not include_archived:
        query = query.where(Podcast.is_archived.is_(False))

    if playlist_id is not None:
        # Existence check only — a filter on an unknown playlist should 404
        # rather than silently return an empty list. Scoped to the user like
        # every other playlist read (issue #182).
        exists = await db.execute(
            select(Playlist.id).where((Playlist.id == playlist_id) & (Playlist.user_id == user_id))
        )
        if exists.scalar_one_or_none() is None:
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
    """Update podcast metadata.

    Archiving hides a podcast from the app while leaving it followed on
    Spotify. It also removes the podcast from every playlist: an archived show
    is invisible in the UI, so letting it keep contributing episodes would be
    a rule nobody can see (issue #247).
    """
    result = await db.execute(select(Podcast).where(Podcast.spotify_id == spotify_id))
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

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
    # Spotify's reported library size, and whether it held still for the whole
    # walk. A total that moves mid-walk means the library changed underneath
    # us, so the pages don't add up to a snapshot of anything (issue #155).
    reported_total: int | None = None
    total_changed = False

    while True:
        # Fetch shows from Spotify
        shows_data = await spotify.get_user_shows(limit=limit, offset=offset)
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
                # Still subscribed: clear any pending unsubscribe mark.
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
                new_count += 1

            synced_count += 1

        offset += limit

        # Check if there are more pages
        if len(items) < limit:
            break

    missing_count, removed_count = await _reconcile_subscriptions(
        db, seen_spotify_ids, None if total_changed else reported_total
    )

    await db.commit()  # persist before the response is sent (see get_db)

    message = "Sync completed"
    if removed_count:
        message += f", removed {removed_count} unsubscribed"
    if missing_count:
        message += f", {missing_count} no longer subscribed (removed after {UNSUBSCRIBE_GRACE.days} days)"

    return {
        "message": message,
        "synced": synced_count,
        "new": new_count,
        "missing": missing_count,
        "removed": removed_count,
    }


async def _reconcile_subscriptions(
    db: AsyncSession, seen_spotify_ids: set[str], reported_total: int | None
) -> tuple[int, int]:
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

    Returns ``(missing, removed)``.
    """
    if reported_total is None or not seen_spotify_ids or len(seen_spotify_ids) < reported_total:
        logger.warning(
            "Skipping subscription reconcile: saw %d shows, Spotify reported %s",
            len(seen_spotify_ids),
            reported_total,
        )
        return 0, 0

    now = datetime.now(UTC)
    result = await db.execute(select(Podcast).where(Podcast.spotify_id.not_in(seen_spotify_ids)))
    missing = result.scalars().all()

    removed = 0
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
            removed += 1

    return len(missing) - removed, removed
