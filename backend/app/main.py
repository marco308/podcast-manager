"""FastAPI Application Entry Point."""

import hmac
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import metrics
from app.config import get_settings
from app.jobs import locks
from app.jobs.scheduler import init_scheduler, shutdown_scheduler
from app.observability import (
    ERROR_LOGGER,
    REQUEST_ID_HEADER,
    REQUEST_ID_SCOPE_KEY,
    ObservabilityMiddleware,
    configure_logging,
    current_request_id,
    route_template,
)
from app.rate_limit import limiter
from app.routers import auth_router, jobs_router, playlists_router, podcasts_router
from app.routers._deps import ReauthRequired, reauth_required_handler
from app.schemas.common import HealthResponse

settings = get_settings()

# One stdout handler for every logger: JSON in production, text with DEBUG
# (LOG_FORMAT overrides). See app/observability.py.
configure_logging(settings.log_format, logging.DEBUG if settings.DEBUG else logging.INFO)

logger = logging.getLogger(__name__)
error_logger = logging.getLogger(ERROR_LOGGER)


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


def docs_urls(debug: bool) -> dict[str, str | None]:
    """The interactive docs and the OpenAPI schema are served only with DEBUG.

    In production they would publish a map of every endpoint and parameter to
    anyone who can reach the API host; nothing in the repo consumes the schema.
    """
    if not debug:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/api/docs", "redoc_url": "/api/redoc", "openapi_url": "/api/openapi.json"}


app = FastAPI(
    title=settings.APP_NAME,
    description="Podcast management and playlist automation",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    **docs_urls(settings.DEBUG),
)

# Rate-limit setup — the Limiter itself is applied via decorators on the
# expensive endpoints. This wires up the 429 handler and middleware.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Unreadable stored credentials: a 401 that also clears the session cookies.
app.add_exception_handler(ReauthRequired, reauth_required_handler)


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
    # The observability middleware has already returned by the time
    # ServerErrorMiddleware calls this, so the id comes from the scope.
    request_id = request.scope.get(REQUEST_ID_SCOPE_KEY) or current_request_id()
    route = route_template(request.scope)
    # Route template, not the URL: the query string is never logged.
    error_logger.error(
        f"Unhandled {type(exc).__name__} in {request.method} {route}",
        exc_info=exc,
        extra={"method": request.method, "route": route, "request_id": request_id},
    )
    # This handler runs outside CORSMiddleware, so without these headers the
    # browser hides the 500 behind a CORS/network error (issue #182). Mirror
    # the middleware config: echo the Origin only if it's one we allow, and
    # include credentials since the middleware does.
    # ServerErrorMiddleware sits outside SecurityHeadersMiddleware, so add
    # the security headers here too.
    headers = security_headers(request.url.path)
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id
    origin = request.headers.get("origin")
    if origin and origin in cors_origins:
        headers |= {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred. Please try again later.",
            "path": str(request.url.path),
            "request_id": request_id,
        },
        headers=headers,
    )


# Sent on every API response. The API host is routed straight to the backend
# by Traefik in the example stack, so nginx's headers don't cover it. The API
# only returns JSON and redirects, so the CSP allows nothing at all.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_API_CSP = "default-src 'none'; frame-ancestors 'none'"
# Swagger UI and ReDoc (DEBUG only) load scripts and styles from a CDN.
_DOCS_PATHS = ("/api/docs", "/api/redoc")


def security_headers(path: str) -> dict[str, str]:
    """A fresh dict of the security headers for a response to ``path``."""
    if path.startswith(_DOCS_PATHS):
        return dict(_SECURITY_HEADERS)
    return {**_SECURITY_HEADERS, "Content-Security-Policy": _API_CSP}


class SecurityHeadersMiddleware:
    """Adds ``security_headers`` to every HTTP response.

    Pure ASGI (it only rewrites the ``http.response.start`` message) for the
    same reason as ``AccountWriteGateMiddleware``: ``BaseHTTPMiddleware``
    would end the request before ``get_db``'s after-response commit. A header
    the endpoint already set is left alone.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        extra = security_headers(scope["path"])

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                for name, value in extra.items():
                    key = name.lower().encode()
                    if key not in present:
                        headers.append((key, value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


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

# Added after the others, so outermost: CORS preflights and rejections get the headers too.
app.add_middleware(SecurityHeadersMiddleware)

# Outermost of all: every response (security-header and CORS rejections
# included) is timed, counted, logged and carries X-Request-ID.
app.add_middleware(ObservabilityMiddleware)

# Include routers
app.include_router(auth_router, prefix="/api")
app.include_router(podcasts_router, prefix="/api")
app.include_router(playlists_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")


@app.get("/api/health", response_model=HealthResponse)
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "commit": settings.GIT_SHA,
    }


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request) -> Response:
    """Prometheus scrape endpoint, guarded by ``METRICS_TOKEN``.

    The API host is reachable from the internet, so without a configured
    token, or without the right bearer, this answers the same 404 as a route
    that doesn't exist rather than revealing it.
    """
    expected = get_settings().METRICS_TOKEN
    provided = _bearer_token(request)
    if not expected or provided is None or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=404, detail="Not Found")
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)
