"""FastAPI Application Entry Point."""

import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.jobs import locks
from app.jobs.scheduler import init_scheduler, shutdown_scheduler
from app.rate_limit import limiter
from app.routers import auth_router, jobs_router, playlists_router, podcasts_router

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

# Reduce noise from third-party libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan manager."""
    logger.info("Starting Podcast Manager API...")
    # Startup. The schema is owned by Alembic and applied by entrypoint.sh
    # before the server boots — the app no longer creates tables itself
    # (issue #149).
    await init_scheduler()
    logger.info("Application started successfully")
    yield
    # Shutdown
    logger.info("Shutting down application...")
    shutdown_scheduler()
    logger.info("Application shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    description="Podcast management and playlist automation",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Rate-limit setup — the Limiter itself is applied via decorators on the
# expensive endpoints. This wires up the 429 handler and middleware.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# CORS origins - restrict based on environment (shared by the middleware and
# the global exception handler below)
cors_origins = [settings.FRONTEND_URL]
if settings.DEBUG:
    cors_origins.extend(
        [
            "https://127.0.0.1:3000",
            "https://localhost:3000",
            "http://localhost:5173",
            "http://localhost:3000",
        ]
    )


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle uncaught exceptions globally."""
    logger.exception(f"Unhandled exception for {request.method} {request.url}: {exc}")
    # This handler runs outside CORSMiddleware, so without these headers the
    # browser hides the 500 behind a CORS/network error (issue #182). Mirror
    # the middleware config: echo the Origin only if it's one we allow, and
    # include credentials since the middleware does.
    headers = {}
    origin = request.headers.get("origin")
    if origin and origin in cors_origins:
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred. Please try again later.",
            "path": str(request.url.path),
        },
        headers=headers,
    )


_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AccountWriteGateMiddleware:
    """Holds ``locks.account_write_gate`` shared for every mutating request.

    Pure ASGI rather than ``@app.middleware``: ``BaseHTTPMiddleware`` returns
    once the response starts, but ``get_db``'s backstop commit runs after the
    response is sent, and that write must stay inside the gate too. The
    account delete itself is exempt; it takes the gate exclusively.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in _MUTATING_METHODS
            or (scope["method"] == "DELETE" and scope["path"] == "/api/auth/me")
        ):
            await self.app(scope, receive, send)
            return
        async with locks.account_write_gate.shared():
            await self.app(scope, receive, send)


app.add_middleware(AccountWriteGateMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix="/api")
app.include_router(podcasts_router, prefix="/api")
app.include_router(playlists_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")


@app.get("/api/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
