"""Structured logging, request ids and the per-request access log + metrics.

Three named loggers keep the streams apart:

- ``podcast_manager.http``: one line per request (replaces uvicorn's access
  log, which ``entrypoint.sh`` turns off): method, route template, status,
  duration_ms, request_id. Never the query string or a body.
- ``podcast_manager.events``: named domain events, e.g. every job run's
  outcome (see ``app.jobs.sync_log``).
- ``podcast_manager.error``: unhandled exceptions, with traceback.

Every record is one line on stdout: JSON in production, plain text locally
(``LOG_FORMAT`` overrides). Log ids, never contents: no tokens, cookies,
emails or Spotify data.
"""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from app import metrics

HTTP_LOGGER = "podcast_manager.http"
EVENTS_LOGGER = "podcast_manager.events"
ERROR_LOGGER = "podcast_manager.error"

REQUEST_ID_HEADER = "X-Request-ID"
# Where the middleware leaves the id for code that runs after it has
# returned: Starlette's ServerErrorMiddleware calls the 500 handler outside
# every user middleware, by which point the contextvar has been reset.
REQUEST_ID_SCOPE_KEY = "podcast_manager.request_id"

# An inbound id is kept only if it is short and plain; anything else (too
# long, spaces, quotes, control characters) is replaced by a fresh one rather
# than repaired, so a client can't inject into log lines or headers.
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_events_logger = logging.getLogger(EVENTS_LOGGER)
_http_logger = logging.getLogger(HTTP_LOGGER)


def new_request_id() -> str:
    return uuid.uuid4().hex


def sanitise_request_id(raw: str | None) -> str:
    """``raw`` if it is a safe inbound id, otherwise a freshly minted one."""
    if raw and _REQUEST_ID_RE.fullmatch(raw):
        return raw
    return new_request_id()


def current_request_id() -> str | None:
    return request_id_var.get()


def log_event(event: str, **fields) -> None:
    """Emit a named domain event on ``podcast_manager.events``."""
    _events_logger.info(event, extra={"event": event, **fields})


# --- formatting --------------------------------------------------------------

# Attributes every LogRecord has; anything else on a record came from
# ``extra=`` and is emitted as a field. ``color_message`` is uvicorn's
# ANSI-coloured duplicate of the message.
_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "color_message",
}


def _extras(record: logging.LogRecord) -> dict:
    return {k: v for k, v in vars(record).items() if k not in _RECORD_ATTRS and not k.startswith("_")}


def _request_id_for(record: logging.LogRecord) -> str | None:
    return getattr(record, "request_id", None) or request_id_var.get()


class JsonFormatter(logging.Formatter):
    """One JSON object per record: timestamp, level, logger, message,
    request_id (when there is one), any ``extra`` fields, and the traceback
    as ``exc_info`` when the record carries one."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = _request_id_for(record)
        if request_id:
            payload["request_id"] = request_id
        for key, value in _extras(record).items():
            payload.setdefault(key, value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """The previous plain-text format, with request_id and extras appended as
    ``key=value`` so local logs carry the same information."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = {}
        request_id = _request_id_for(record)
        if request_id:
            fields["request_id"] = request_id
        fields.update({k: v for k, v in _extras(record).items() if k != "request_id"})
        if not fields:
            return line
        suffix = " ".join(f"{k}={v}" for k, v in fields.items())
        head, sep, rest = line.partition("\n")  # keep a traceback after the fields
        return f"{head} [{suffix}]{sep}{rest}"


def configure_logging(log_format: str, level: int) -> None:
    """Route every logger through one stdout handler with the chosen format.

    uvicorn installs its own handlers on ``uvicorn`` and ``uvicorn.access``
    before the app is imported; those are stripped so its lines go through
    the same formatter, and its access log is silenced (``podcast_manager.http``
    replaces it; ``entrypoint.sh`` also passes ``--no-access-log``).
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if log_format == "json" else TextFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True
    logging.getLogger("uvicorn.access").disabled = True

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


# --- middleware --------------------------------------------------------------


def route_template(scope) -> str:
    """The matched route's full path template, or ``unmatched``.

    Since FastAPI 0.15x, ``include_router`` no longer copies routes into the
    app with the prefix baked in: ``scope["route"]`` is the router's own
    ``APIRoute``, whose ``path`` lacks the ``/api`` include prefix. The full
    template is on the effective route context FastAPI records in the scope
    (the same value it reports as ``http.route`` to OpenTelemetry). That key
    is not public API, so it is read defensively, and
    ``test_observability`` pins the result (``/api/playlists/{playlist_id}``)
    so an upgrade that moves it fails CI rather than mislabelling metrics.
    """
    fastapi_scope = scope.get("fastapi")
    context = fastapi_scope.get("effective_route_context") if isinstance(fastapi_scope, dict) else None
    if context is not None:
        path = getattr(getattr(context, "starlette_route", None), "path_format", None) or getattr(
            context, "path_format", None
        )
        if isinstance(path, str) and path:
            return path
    route = scope.get("route")
    path = getattr(route, "path_format", None) or getattr(route, "path", None)
    return path if isinstance(path, str) and path else metrics.UNMATCHED_ROUTE


class ObservabilityMiddleware:
    """Request id, access log line and HTTP metrics for every request.

    Pure ASGI, like the repo's other middlewares, so it never ends a request
    before ``get_db``'s after-response commit. Added last, so it is the
    outermost user middleware: it sees the final status of everything the
    others produce. The route template is read from ``scope["route"]``, which
    Starlette's router sets on this same scope dict once it has matched.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                inbound = value.decode("latin-1")
                break
        request_id = sanitise_request_id(inbound)
        scope[REQUEST_ID_SCOPE_KEY] = request_id
        token = request_id_var.set(request_id)

        status = 500
        start = time.perf_counter()

        async def send_with_id(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            # On an exception, ServerErrorMiddleware (outside this one) sends
            # the 500, so ``status`` keeps its 500 default.
            duration = time.perf_counter() - start
            method = scope["method"]
            route = route_template(scope)
            metrics.observe_request(method, route, status, duration)
            _http_logger.info(
                f"{method} {route} {status}",
                extra={
                    "method": method,
                    "route": route,
                    "status": status,
                    "duration_ms": round(duration * 1000, 2),
                    "request_id": request_id,
                },
            )
            request_id_var.reset(token)
