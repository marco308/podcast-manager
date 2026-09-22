"""API Routers."""

from app.routers.auth import router as auth_router
from app.routers.jobs import router as jobs_router
from app.routers.playlists import router as playlists_router
from app.routers.podcasts import router as podcasts_router

__all__ = ["auth_router", "podcasts_router", "playlists_router", "jobs_router"]
