"""Playlists router for managing playlist configurations."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.playlist import Playlist, PlaylistRuleType
from app.routers.auth import get_current_user_id
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistResponse,
    PlaylistUpdate,
    PlaylistListResponse,
)

router = APIRouter(prefix="/playlists", tags=["Playlists"])


@router.get("", response_model=PlaylistListResponse)
async def list_playlists(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PlaylistListResponse:
    """List all managed playlists."""
    result = await db.execute(select(Playlist).order_by(Playlist.name))
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
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
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
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
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
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
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
    """Manually trigger a playlist update (stub for Phase 3)."""
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
    playlist = result.scalar_one_or_none()

    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # TODO: Implement playlist update logic in Phase 3
    playlist.last_updated_at = datetime.utcnow()
    await db.flush()

    return {
        "message": f"Playlist '{playlist.name}' update triggered",
        "playlist_id": playlist_id,
    }


@router.post("/run-all")
async def run_all_playlist_updates(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger all playlist updates (stub for Phase 3)."""
    result = await db.execute(
        select(Playlist).where(Playlist.is_enabled == True)
    )
    playlists = result.scalars().all()

    # TODO: Implement playlist update logic in Phase 3
    for playlist in playlists:
        playlist.last_updated_at = datetime.utcnow()

    await db.flush()

    return {
        "message": "All playlist updates triggered",
        "count": len(playlists),
    }
