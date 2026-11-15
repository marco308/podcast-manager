"""Structured logs, request ids and /metrics (the homelab service conventions)."""

import json
import logging

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.jobs.sync_log import sync_log_run
from app.main import app
from app.metrics import REGISTRY
from app.models import Base
from app.models.sync_log import SyncStatus
from app.observability import (
    EVENTS_LOGGER,
    HTTP_LOGGER,
    JsonFormatter,
    TextFormatter,
    request_id_var,
    sanitise_request_id,
)
from tests.job_patches import patch_job_sessions

TOKEN = "metrics-test-token"


@pytest.fixture
def client():
    return TestClient(app)


def _blow_up(message: str) -> None:
    """Raise from a helper, so the code after ``pytest.raises`` isn't read as
    unreachable by static analysis (it runs: pytest.raises swallows this)."""
    raise RuntimeError(message)


def _records(caplog, logger_name):
    return [r for r in caplog.records if r.name == logger_name]


# --- request id ---------------------------------------------------------------


class TestRequestId:
    def test_minted_when_absent(self, client):
        rid = client.get("/api/health").headers["x-request-id"]
        assert len(rid) == 32
        assert client.get("/api/health").headers["x-request-id"] != rid

    def test_inbound_id_is_honoured(self, client):
        response = client.get("/api/health", headers={"X-Request-ID": "abc-123.def_456:7"})
        assert response.headers["x-request-id"] == "abc-123.def_456:7"

    @pytest.mark.parametrize("bad", ["x" * 65, "has space", 'quote"d', "semi;colon", "new\tline"])
    def test_unsafe_inbound_id_is_replaced(self, client, bad):
        rid = client.get("/api/health", headers={"X-Request-ID": bad}).headers["x-request-id"]
        assert rid != bad
        assert len(rid) == 32

    def test_sanitise(self):
        assert sanitise_request_id("ok-1") == "ok-1"
        assert sanitise_request_id("") != ""
        assert sanitise_request_id(None)
        assert sanitise_request_id("<script>") != "<script>"

    def test_on_error_responses(self, client):
        assert client.get("/api/nope").headers["x-request-id"]
        assert client.get("/api/auth/me").headers["x-request-id"]  # 401

    def test_contextvar_is_cleared_after_the_request(self, client):
        client.get("/api/health")
        assert request_id_var.get() is None


@pytest.fixture
def boom_route():
    async def boom(thing_id: int):
        raise RuntimeError("kaboom secret-ish detail")

    app.add_api_route("/api/_test_boom/{thing_id}", boom, methods=["GET"])
    try:
        yield
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", None) != "/api/_test_boom/{thing_id}"
        ]


class TestUnhandledException:
    def test_500_body_keeps_its_shape_and_adds_the_request_id(self, boom_route, caplog):
        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level(logging.INFO):
            response = client.get("/api/_test_boom/7?q=private", headers={"X-Request-ID": "req-500"})

        assert response.status_code == 500
        assert response.json() == {
            "detail": "An internal server error occurred. Please try again later.",
            "path": "/api/_test_boom/7",
            "request_id": "req-500",
        }
        assert response.headers["x-request-id"] == "req-500"

        [error] = _records(caplog, "podcast_manager.error")
        assert error.request_id == "req-500"
        assert error.route == "/api/_test_boom/{thing_id}"
        assert error.exc_info is not None
        line = json.loads(JsonFormatter().format(error))
        assert "RuntimeError: kaboom" in line["exc_info"]
        assert "private" not in line["message"]

        [access] = _records(caplog, HTTP_LOGGER)
        assert (access.status, access.route, access.request_id) == (500, "/api/_test_boom/{thing_id}", "req-500")


# --- log format ---------------------------------------------------------------


def _record(name="podcast_manager.events", msg="hello", extra=None, exc_info=None):
    record = logging.getLogger(name).makeRecord(name, logging.INFO, "f.py", 1, msg, (), exc_info, extra=extra)
    return record


class TestFormatters:
    def test_json_line_parses_and_carries_fields(self):
        token = request_id_var.set("rid-1")
        try:
            line = JsonFormatter().format(_record(extra={"job_type": "cleanup", "count": 3}))
        finally:
            request_id_var.reset(token)
        assert "\n" not in line
        payload = json.loads(line)
        assert payload["level"] == "INFO"
        assert payload["logger"] == "podcast_manager.events"
        assert payload["message"] == "hello"
        assert payload["request_id"] == "rid-1"
        assert payload["job_type"] == "cleanup"
        assert payload["count"] == 3
        assert payload["timestamp"].endswith("+00:00")

    def test_json_without_request_id_omits_it(self):
        assert "request_id" not in json.loads(JsonFormatter().format(_record()))

    def test_json_traceback_stays_on_one_line(self):
        try:
            raise ValueError("bad")
        except ValueError:
            import sys

            line = JsonFormatter().format(_record(exc_info=sys.exc_info()))
        assert "\n" not in line
        assert "ValueError: bad" in json.loads(line)["exc_info"]

    def test_text_appends_request_id_and_extras(self):
        line = TextFormatter().format(_record(extra={"request_id": "r9", "job_type": "cleanup"}))
        assert line.endswith("hello [request_id=r9 job_type=cleanup]")

    def test_log_format_defaults(self):
        assert Settings(_env_file=None, DEBUG=False).log_format == "json"
        assert Settings(_env_file=None, DEBUG=True).log_format == "text"
        assert Settings(_env_file=None, DEBUG=True, LOG_FORMAT="JSON").log_format == "json"
        with pytest.raises(ValueError):
            Settings(_env_file=None, LOG_FORMAT="xml")


class TestAccessLog:
    def test_one_line_with_route_template_not_raw_path(self, client, caplog):
        with caplog.at_level(logging.INFO, logger=HTTP_LOGGER):
            client.get("/api/playlists/42?secret=1", headers={"X-Request-ID": "rid-http"})
        [record] = _records(caplog, HTTP_LOGGER)
        payload = json.loads(JsonFormatter().format(record))
        assert payload["route"] == "/api/playlists/{playlist_id}"
        assert payload["method"] == "GET"
        assert payload["status"] == 401
        assert payload["request_id"] == "rid-http"
        assert isinstance(payload["duration_ms"], float)
        assert "42" not in payload["message"]
        assert "secret" not in json.dumps(payload)

    def test_unmatched_path(self, client, caplog):
        with caplog.at_level(logging.INFO, logger=HTTP_LOGGER):
            client.get("/no/such/thing")
        [record] = _records(caplog, HTTP_LOGGER)
        assert (record.route, record.status) == ("unmatched", 404)

    def test_healthcheck_polls_are_counted_but_not_logged(self, client, caplog):
        """The healthcheck runs every few seconds; its successes would bury
        real requests in Loki, but they still reach the metrics."""
        with caplog.at_level(logging.INFO, logger=HTTP_LOGGER):
            response = client.get("/api/health")
        assert response.status_code == 200
        assert _records(caplog, HTTP_LOGGER) == []
        sample = REGISTRY.get_sample_value(
            "http_requests_total", {"method": "GET", "route": "/api/health", "status": "200"}
        )
        assert sample and sample >= 1


# --- /metrics -----------------------------------------------------------------


@pytest.fixture
def metrics_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "METRICS_TOKEN", TOKEN)
    return TOKEN


class TestMetricsEndpoint:
    def test_404_without_a_configured_token(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "METRICS_TOKEN", "")
        assert client.get("/metrics").status_code == 404
        assert client.get("/metrics", headers={"Authorization": "Bearer "}).status_code == 404

    @pytest.mark.parametrize(
        "headers",
        [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}, {"Authorization": TOKEN}],
    )
    def test_404_without_the_right_bearer(self, client, metrics_token, headers):
        response = client.get("/metrics", headers=headers)
        assert response.status_code == 404
        assert response.json() == client.get("/no/such/route").json()

    def test_200_with_the_right_bearer(self, client, metrics_token):
        client.get("/api/health")
        response = client.get("/metrics", headers={"Authorization": f"Bearer {metrics_token}"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        body = response.text
        for name in (
            "http_requests_total",
            "http_request_duration_seconds_bucket",
            "job_runs_total",
            "job_last_run_timestamp_seconds",
            "spotify_api_calls_total",
        ):
            assert name in body
        # The private registry only: no default process/platform collectors.
        assert "python_info" not in body

    def test_route_label_is_the_template(self, client):
        def count(route, status):
            return (
                REGISTRY.get_sample_value("http_requests_total", {"method": "GET", "route": route, "status": status})
                or 0
            )

        before = count("/api/playlists/{playlist_id}", "401")
        client.get("/api/playlists/123")
        assert count("/api/playlists/{playlist_id}", "401") == before + 1
        assert (
            REGISTRY.get_sample_value(
                "http_requests_total", {"method": "GET", "route": "/api/playlists/123", "status": "401"}
            )
            is None
        )

        before = count("unmatched", "404")
        client.get("/definitely/not/here")
        assert count("unmatched", "404") == before + 1

    def test_non_standard_method_is_folded(self, client):
        before = (
            REGISTRY.get_sample_value("http_requests_total", {"method": "OTHER", "route": "unmatched", "status": "404"})
            or 0
        )
        client.request("BREW", "/nowhere")
        after = REGISTRY.get_sample_value(
            "http_requests_total", {"method": "OTHER", "route": "unmatched", "status": "404"}
        )
        assert after == before + 1


class TestMetricsTokenSources:
    def test_env_wins(self, tmp_path):
        secret = tmp_path / "token"
        secret.write_text("from-file\n")
        assert Settings(_env_file=None, METRICS_TOKEN=" env ", METRICS_TOKEN_FILE=str(secret)).METRICS_TOKEN == "env"

    def test_file(self, tmp_path):
        secret = tmp_path / "token"
        secret.write_text("from-file\n")
        assert Settings(_env_file=None, METRICS_TOKEN_FILE=str(secret)).METRICS_TOKEN == "from-file"

    def test_named_file_missing_fails_startup(self, tmp_path):
        with pytest.raises(ValueError, match="METRICS_TOKEN_FILE"):
            Settings(_env_file=None, METRICS_TOKEN_FILE=str(tmp_path / "absent"))

    def test_docker_secret_fallback(self, tmp_path, monkeypatch):
        secret = tmp_path / "metrics_token"
        secret.write_text("swarm-secret")
        monkeypatch.setattr("app.config.DOCKER_METRICS_TOKEN_SECRET", secret)
        assert Settings(_env_file=None).METRICS_TOKEN == "swarm-secret"

    def test_unset(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.DOCKER_METRICS_TOKEN_SECRET", tmp_path / "absent")
        assert Settings(_env_file=None).METRICS_TOKEN == ""


# --- job runs -----------------------------------------------------------------


@pytest_asyncio.fixture
async def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/runs.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        with patch_job_sessions(session_maker):
            yield session_maker
    finally:
        await engine.dispose()


def _job_runs(job_type, outcome):
    return REGISTRY.get_sample_value("job_runs_total", {"job_type": job_type, "outcome": outcome}) or 0


class TestJobRunEvents:
    @pytest.mark.asyncio
    async def test_success_emits_event_and_counts(self, maker, caplog):
        before = _job_runs("cleanup", "ok")
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            async with sync_log_run("cleanup") as run:
                run.finish(
                    status=SyncStatus.SUCCESS,
                    details="Removed 2 episodes from 'My private playlist'",
                    failure_code=None,
                    playlists_attempted=3,
                    api_calls_used=9,
                )

        assert _job_runs("cleanup", "ok") == before + 1
        assert REGISTRY.get_sample_value("job_last_run_timestamp_seconds", {"job_type": "cleanup", "outcome": "ok"}) > 0
        [event] = _records(caplog, EVENTS_LOGGER)
        payload = json.loads(JsonFormatter().format(event))
        assert payload["message"] == "job_run"
        assert payload["event"] == "job_run"
        assert payload["outcome"] == "ok"
        assert payload["job_type"] == "cleanup"
        assert payload["sync_log_id"] == run.id
        assert payload["playlists_attempted"] == 3
        assert payload["api_calls_used"] == 9
        assert payload["failure_code"] is None
        # details can carry user-chosen names; it stays in the SyncLog row.
        assert "My private playlist" not in json.dumps(payload)

    @pytest.mark.asyncio
    async def test_exception_is_an_error_run(self, maker, caplog):
        before = _job_runs("playlist_update", "error")
        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER), pytest.raises(RuntimeError):
            async with sync_log_run("playlist_update"):
                _blow_up("boom")

        assert _job_runs("playlist_update", "error") == before + 1
        [event] = _records(caplog, EVENTS_LOGGER)
        assert (event.outcome, event.failure_code) == ("error", "unknown")
