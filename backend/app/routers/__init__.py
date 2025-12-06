"""API Routers."""

from app.routers.auth import router as auth_router
from app.routers.podcasts import router as podcasts_router
from app.routers.playlists import router as playlists_router

__all__ = ["auth_router", "podcasts_router", "playlists_router"]
