from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from memtrace_api.config import PROJECT_ROOT, Settings
from memtrace_api.database import session_scope
from memtrace_api.db_models import TaskModel, UserModel
from memtrace_api.main import _valid_last_event_id, create_app
from memtrace_api.schemas import utc_now

TASK_ID = "task_01J00000000000000000000001"
TEST_SESSION_SECRET = "test_session_secret_01234567890123456789"


@dataclass
class _DummyRecord:
    user_ctx: Any = None


@dataclass
class ClosedSubscription:
    replay: list[Any] = field(default_factory=list)
    subscriber: None = None
    closed_at_capture: bool = True
    _record: _DummyRecord = field(default_factory=_DummyRecord)

    async def close(self) -> None:
        return None


@dataclass
class CursorStore:
    calls: list[tuple[int, int]] = field(default_factory=list)

    async def open_subscription(
        self,
        task_id: str,
        *,
        after_event_seq: int,
        after_offset: int,
    ) -> ClosedSubscription:
        assert task_id == TASK_ID
        self.calls.append((after_event_seq, after_offset))
        return ClosedSubscription()

    async def cancel_workers(self) -> None:
        return None


def _client(tmp_path: Path, store: CursorStore) -> TestClient:
    db_url = f"sqlite:///{(tmp_path / 'test.sqlite3').as_posix()}"
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
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        mock_mode=True,
        memtrace_data_dir=tmp_path / "data",
        memtrace_database_url=db_url,
        session_secret=TEST_SESSION_SECRET,
    )
    client = TestClient(create_app(settings, store=store))
    login = client.post("/api/v1/session/demo", json={"demo_alias": "blank_demo"})
    assert login.status_code == 200, login.text

    # Insert a task row owned by the logged-in user so the owner check passes.
    factory = client.app.state.db_session_factory
    with session_scope(factory) as session:
        user = session.execute(
            select(UserModel).where(UserModel.demo_alias == "blank_demo")
        ).scalar_one()
        session.add(
            TaskModel(
                id=TASK_ID,
                owner_id=user.id,
                scenario="programming_learning",
                task_text="测试",
                effective_memory_mode="on",
                status="active",
                next_event_seq=1,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    return client


def test_valid_last_event_id_and_explicit_query_precedence(tmp_path: Path) -> None:
    store = CursorStore()
    with _client(tmp_path, store) as client:
        from_header = client.get(
            f"/api/v1/tasks/{TASK_ID}/events?after_offset=12",
            headers={"Last-Event-ID": "7"},
        )
        explicit_query = client.get(
            f"/api/v1/tasks/{TASK_ID}/events?after_event_seq=3&after_offset=9",
            headers={"Last-Event-ID": "7"},
        )
    assert from_header.status_code == 200
    assert explicit_query.status_code == 200
    assert store.calls == [(7, 12), (3, 9)]


def test_invalid_or_pathological_last_event_id_safely_falls_back_to_zero(
    tmp_path: Path,
) -> None:
    store = CursorStore()
    assert _valid_last_event_id("１２") == 0
    with _client(tmp_path, store) as client:
        huge = client.get(
            f"/api/v1/tasks/{TASK_ID}/events",
            headers={"Last-Event-ID": "9" * 5_000},
        )
    assert huge.status_code == 200
    assert store.calls == [(0, 0)]
