"""Playlists router for managing playlist configurations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.playlist import Playlist, PlaylistRuleType
from app.models.user import User
from app.routers.auth import get_current_user_id
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistResponse,
    PlaylistUpdate,
    PlaylistListResponse,
)
from app.services.playlist_builder import PlaylistBuilder

router = APIRouter(prefix="/playlists", tags=["Playlists"])


@router.get("", response_model=PlaylistListResponse)
async def list_playlists(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PlaylistListResponse:
    """List all managed playlists."""
    result = await db.execute(
        select(Playlist).where(Playlist.user_id == user_id).order_by(Playlist.name)
    )
    playlists = result.scalars().all()

    return PlaylistListResponse(items=list(playlists), total=len(playlists))


@router.post("", response_model=PlaylistResponse)
async def create_playlist(
    playlist_data: PlaylistCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Playlist:
    """Create a new playlist mapping."""
    playlist = Playlist(
        user_id=user_id,
        name=playlist_data.name,
        spotify_playlist_id=playlist_data.spotify_playlist_id,
        rule_type=PlaylistRuleType(playlist_data.rule_type.value),
        is_enabled=playlist_data.is_enabled,
    )
    db.add(playlist)
    await db.flush()

    return playlist


@router.get("/{playlist_id}", response_model=PlaylistResponse)
async def get_playlist(
    playlist_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Playlist:
    """Get a playlist by ID."""
    result = await db.execute(
        select(Playlist).where(
            (Playlist.id == playlist_id) & (Playlist.user_id == user_id)
        )
    )
    playlist = result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    return playlist


@router.patch("/{playlist_id}", response_model=PlaylistResponse)
async def update_playlist(
    playlist_id: int,
    update_data: PlaylistUpdate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Playlist:
    """Update playlist configuration."""
    result = await db.execute(
        select(Playlist).where(
            (Playlist.id == playlist_id) & (Playlist.user_id == user_id)
        )
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

    await db.flush()
    return playlist


@router.delete("/{playlist_id}")
async def delete_playlist(
    playlist_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a playlist mapping."""
    result = await db.execute(
        select(Playlist).where(
            (Playlist.id == playlist_id) & (Playlist.user_id == user_id)
        )
    )
    playlist = result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    await db.delete(playlist)
    return {"message": "Playlist deleted"}


@router.post("/{playlist_id}/run")
async def run_playlist_update(
    playlist_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger a playlist update."""
    # Get the playlist
    playlist_result = await db.execute(
        select(Playlist).where(
            (Playlist.id == playlist_id) & (Playlist.user_id == user_id)
        )
    )
    playlist = playlist_result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Get the user
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Build and update the playlist
    builder = PlaylistBuilder(db, user)
    result = await builder.update_playlist(playlist)

    if not result.success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update playlist: {result.error}",
        )

    return {
        "message": f"Playlist '{playlist.name}' updated successfully",
        "playlist_id": playlist_id,
        "episode_count": result.episode_count,
    }


@router.post("/run-all")
async def run_all_playlist_updates(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger all enabled playlist updates."""
    # Get the user
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update all playlists
    builder = PlaylistBuilder(db, user)
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
