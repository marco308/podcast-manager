"""Podcasts router for managing podcast metadata."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.podcast import Podcast, PodcastCategory
from app.models.user import User
from app.routers.auth import get_current_user_id
from app.schemas.podcast import (
    PodcastResponse,
    PodcastUpdate,
    PodcastListResponse,
    PodcastCategory as PodcastCategorySchema,
)
from app.services.encryption import get_encryption_service
from app.services.spotify import SpotifyService

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
    access_token = encryption.decrypt(user.access_token)

    return user, access_token


@router.get("", response_model=PodcastListResponse)
async def list_podcasts(
    category: Optional[PodcastCategorySchema] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PodcastListResponse:
    """List all podcasts with optional category filter."""
    query = select(Podcast)

    if category:
        query = query.where(Podcast.category == PodcastCategory(category.value))

    # Get total count
    count_query = select(func.count()).select_from(Podcast)
    if category:
        count_query = count_query.where(Podcast.category == PodcastCategory(category.value))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    query = query.order_by(Podcast.name).offset(offset).limit(limit)
    result = await db.execute(query)
    podcasts = result.scalars().all()

    return PodcastListResponse(items=list(podcasts), total=total)


@router.get("/{spotify_id}", response_model=PodcastResponse)
async def get_podcast(
    spotify_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Podcast:
    """Get a single podcast by Spotify ID."""
    result = await db.execute(
        select(Podcast).where(Podcast.spotify_id == spotify_id)
    )
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    return podcast


@router.patch("/{spotify_id}", response_model=PodcastResponse)
async def update_podcast(
    spotify_id: str,
    update_data: PodcastUpdate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Podcast:
    """Update podcast metadata (category, attributes)."""
    result = await db.execute(
        select(Podcast).where(Podcast.spotify_id == spotify_id)
    )
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    # Update fields if provided
    if update_data.category is not None:
        podcast.category = PodcastCategory(update_data.category.value)
    if update_data.is_sequential is not None:
        podcast.is_sequential = update_data.is_sequential
    if update_data.is_weekend_only is not None:
        podcast.is_weekend_only = update_data.is_weekend_only
    if update_data.morning_order is not None:
        podcast.morning_order = update_data.morning_order
    if update_data.playlist_order is not None:
        podcast.playlist_order = update_data.playlist_order

    podcast.updated_at = datetime.utcnow()

    await db.flush()
    return podcast


@router.delete("/{spotify_id}")
async def unfollow_podcast(
    spotify_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Unfollow a podcast from Spotify and optionally remove from local database."""
    user, access_token = await get_user_with_token(user_id, db)

    # Check if podcast exists in our database
    result = await db.execute(
        select(Podcast).where(Podcast.spotify_id == spotify_id)
    )
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    # Unfollow from Spotify
    spotify = SpotifyService(access_token=access_token)
    try:
        await spotify.unfollow_show(spotify_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to unfollow podcast on Spotify: {str(e)}"
        )

    # Remove from local database
    await db.delete(podcast)
    await db.flush()

    return {"message": f"Successfully unfollowed '{podcast.name}'"}


@router.post("/sync")
async def sync_podcasts(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sync subscribed podcasts from Spotify."""
    user, access_token = await get_user_with_token(user_id, db)

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
            result = await db.execute(
                select(Podcast).where(Podcast.spotify_id == spotify_id)
            )
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
            except Exception:
                # If we can't fetch episodes, keep previous count or 0
                unplayed_count = podcast.unplayed_episodes if podcast else 0

            if podcast:
                # Update existing podcast
                podcast.name = show.get("name", podcast.name)
                podcast.description = show.get("description")
                podcast.image_url = image_url
                podcast.publisher = show.get("publisher")
                podcast.total_episodes = show.get("total_episodes", 0)
                podcast.unplayed_episodes = unplayed_count
                podcast.last_synced_at = datetime.utcnow()
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
                    last_synced_at=datetime.utcnow(),
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
