from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memtrace_api.config import PROJECT_ROOT, Settings
from memtrace_api.main import create_app

TEST_SESSION_SECRET = "test_session_secret_01234567890123456789"


def migrate_database(db_url: str) -> None:
    """Run ``alembic upgrade head`` against an isolated SQLite database."""
    env = dict(os.environ, MEMTRACE_DATABASE_URL=db_url)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(PROJECT_ROOT / "apps" / "api" / "alembic.ini"),
            "upgrade",
            "head",
        ],
        env=env,
        check=True,
        capture_output=True,
        cwd=str(PROJECT_ROOT),
    )


def make_test_client(
    tmp_path: Path,
    *,
    store: object | None = None,
    alias: str = "blank_demo",
    **overrides: object,
) -> TestClient:
    """Build an app against an isolated migrated SQLite DB and log in as a demo user."""
    db_file = tmp_path / "test.sqlite3"
    db_url = f"sqlite:///{db_file.as_posix()}"
    migrate_database(db_url)
    values: dict[str, object] = {
        "app_env": "test",
        "mock_mode": True,
        "memtrace_data_dir": tmp_path / "data",
        "memtrace_database_url": db_url,
        "session_secret": TEST_SESSION_SECRET,
    }
    values.update(overrides)
    settings = Settings(_env_file=None, **values)
    client = TestClient(create_app(settings, store=store))
    login = client.post("/api/v1/session/demo", json={"demo_alias": alias})
    assert login.status_code == 200, login.text
    return client


@pytest.fixture
def tmp_db_url(tmp_path: Path) -> str:
    db_file = tmp_path / "test.sqlite3"
    db_url = f"sqlite:///{db_file.as_posix()}"
    migrate_database(db_url)
    return db_url


@pytest.fixture
def client_factory(tmp_path: Path, tmp_db_url: str) -> Callable[..., TestClient]:
    def build(**overrides: object) -> TestClient:
        db_url = overrides.pop("memtrace_database_url", tmp_db_url)
        values: dict[str, object] = {
            "app_env": "test",
            "mock_mode": True,
            "memtrace_data_dir": tmp_path / "data",
            "memtrace_database_url": db_url,
            "session_secret": TEST_SESSION_SECRET,
        }
        values.update(overrides)
        settings = Settings(_env_file=None, **values)
        return TestClient(create_app(settings))

    return build


@pytest.fixture
def session_client_factory(tmp_path: Path, tmp_db_url: str) -> Callable[..., TestClient]:
    """Return a client factory that logs in as a demo user.

    Each returned client has a valid ``memtrace_demo_session`` cookie and an
    ``Idempotency-Key`` default header suitable for Day 2 write endpoints.
    """

    def build(*, alias: str = "blank_demo", **overrides: object) -> TestClient:
        db_url = overrides.pop("memtrace_database_url", tmp_db_url)
        values: dict[str, object] = {
            "app_env": "test",
            "mock_mode": True,
            "memtrace_data_dir": tmp_path / "data",
            "memtrace_database_url": db_url,
            "session_secret": TEST_SESSION_SECRET,
        }
        values.update(overrides)
        settings = Settings(_env_file=None, **values)
        client = TestClient(
            create_app(settings),
            headers={"Idempotency-Key": "test-idempotency-key-0001"},
        )
        login = client.post("/api/v1/session/demo", json={"demo_alias": alias})
        assert login.status_code == 200, login.text
        return client

    return build
