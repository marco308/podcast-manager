"""Prometheus metrics, on a private registry served at ``GET /metrics``.

A private ``CollectorRegistry`` rather than the global default, so nothing a
library registers on import ends up in the scrape, and tests can read exactly
these series.

Label discipline: ``route`` is the matched route template
(``/api/playlists/{playlist_id}``), never the raw path, and ``unmatched`` when
no route matched; ``method`` is one of the standard verbs or ``OTHER``. Both
keep the series count bounded whatever a client sends.
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    disable_created_metrics,
    generate_latest,
)

# No ``*_created`` companion series: they double the scrape for nothing a
# dashboard here uses.
disable_created_metrics()

REGISTRY = CollectorRegistry(auto_describe=True)

UNMATCHED_ROUTE = "unmatched"

_KNOWN_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

HTTP_REQUESTS = Counter(
    "http_requests",
    "HTTP requests handled, by method, matched route template and status code.",
    ["method", "route", "status"],
    registry=REGISTRY,
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Time from receiving a request to finishing its response, by method and route template.",
    ["method", "route"],
    registry=REGISTRY,
)
JOB_RUNS = Counter(
    "job_runs",
    "Finished job runs (one per SyncLog row), by job type and outcome (ok|error).",
    ["job_type", "outcome"],
    registry=REGISTRY,
)
JOB_LAST_RUN = Gauge(
    "job_last_run_timestamp_seconds",
    "Unix time the most recent run of each job type finished, by outcome (ok|error).",
    ["job_type", "outcome"],
    registry=REGISTRY,
)
SPOTIFY_API_CALLS = Counter(
    "spotify_api_calls",
    "Spotify Web API requests issued (retries included), by response status code, or 'error' for a transport failure.",
    ["status"],
    registry=REGISTRY,
)


def method_label(method: str) -> str:
    """The method as a label value, folding anything non-standard into ``OTHER``."""
    return method if method in _KNOWN_METHODS else "OTHER"


def observe_request(method: str, route: str, status: int, duration_seconds: float) -> None:
    method = method_label(method)
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration_seconds)


def record_job_run(job_type: str, outcome: str, finished_at: float) -> None:
    JOB_RUNS.labels(job_type=job_type, outcome=outcome).inc()
    JOB_LAST_RUN.labels(job_type=job_type, outcome=outcome).set(finished_at)


def render() -> tuple[bytes, str]:
    """The exposition body and its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
