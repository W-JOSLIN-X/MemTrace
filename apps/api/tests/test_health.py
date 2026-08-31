from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from memtrace_api.config import Settings
from memtrace_api.main import create_app

TEST_SESSION_SECRET = "test_session_secret_01234567890123456789"

REQUEST_ID_PATTERN = re.compile(r"^req_[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def test_health_is_liveness_only(client_factory: Callable[..., TestClient]) -> None:
    response = client_factory(mock_mode=False, llm_api_key=None).get("/api/v1/health")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["request_id"] == response.headers["x-request-id"]
    assert body["service"] == "memtrace-api"
    assert body["version"] == "0.1.1"
    assert body["environment"] == "test"
    assert body["at"].endswith("Z")
    assert REQUEST_ID_PATTERN.fullmatch(response.headers["x-request-id"])


def test_mock_mode_is_ready_and_creates_data_dir(
    client_factory: Callable[..., TestClient], tmp_path: Path
) -> None:
    data_dir = tmp_path / "mock-data"
    response = client_factory(mock_mode=True, memtrace_data_dir=data_dir).get("/api/v1/ready")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ready"
    assert body["provider_mode"] == "mock"
    assert body["request_id"] == response.headers["x-request-id"]
    assert body["checks"] == {
        "config": "pass",
        "session_secret": "pass",
        "data_dir": "pass",
        "provider_credentials": "not_required",
        "provider_network": "unchecked",
        "database": "pass",
        "migration_revision": "pass",
    }
    assert data_dir.is_dir()
    assert list(data_dir.iterdir()) == []


def test_real_mode_without_key_is_not_ready(client_factory: Callable[..., TestClient]) -> None:
    response = client_factory(mock_mode=False, llm_api_key=None).get("/api/v1/ready")
    body = response.json()
    assert response.status_code == 503
    assert response.headers["x-request-id"] == body["error"]["request_id"]
    assert body["error"]["code"] == "PROVIDER_CONFIG_MISSING"
    assert body["error"]["retryable"] is False
    assert "LLM_API_KEY" in body["error"]["message"]


def test_production_without_session_secret_is_not_ready(
    client_factory: Callable[..., TestClient],
) -> None:
    response = client_factory(app_env="production", session_secret=None).get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["error"]["details"]["check"] == "session_secret"


def test_real_mode_with_key_is_ready_without_network_probe(
    client_factory: Callable[..., TestClient],
) -> None:
    secret = "unit-test-runtime-key"
    response = client_factory(mock_mode=False, llm_api_key=secret).get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["provider_mode"] == "real"
    assert response.json()["checks"]["provider_credentials"] == "pass"
    assert secret not in response.text


def test_empty_database_is_live_but_not_ready(tmp_path: Path) -> None:
    client = _client_for_unmigrated_database(tmp_path / "empty.sqlite3", tmp_path)
    with client:
        assert client.get("/api/v1/health").status_code == 200
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["error"]["details"]["check"] == "migration_revision"


def test_stale_database_revision_is_not_ready(tmp_path: Path) -> None:
    db_path = tmp_path / "stale.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('obsolete_revision')")

    client = _client_for_unmigrated_database(db_path, tmp_path)
    with client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["error"]["details"]["check"] == "migration_revision"


def test_unknown_route_uses_public_error_envelope(
    client_factory: Callable[..., TestClient],
) -> None:
    response = client_factory().get("/missing")
    body = response.json()
    assert response.status_code == 404
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["request_id"] == response.headers["x-request-id"]


def _client_for_unmigrated_database(db_path: Path, tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        app_env="test",
        mock_mode=True,
        memtrace_data_dir=tmp_path / "data",
        memtrace_database_url=f"sqlite:///{db_path.as_posix()}",
        session_secret=TEST_SESSION_SECRET,
    )
    return TestClient(create_app(settings))
