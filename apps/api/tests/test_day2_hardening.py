"""Concurrency, capacity-admission, and idempotency hardening for Day 2."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from memtrace_api.config import Settings
from memtrace_api.database import create_db_engine, create_session_factory, session_scope
from memtrace_api.db_models import (
    AgentRunModel,
    EventLogModel,
    IdempotencyKeyModel,
    MessageModel,
    TaskModel,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.logic import analyze_task
from memtrace_api.main import create_app
from memtrace_api.repositories import TaskRepository, UserContext, UserRepository
from memtrace_api.schemas import ProviderMode, TaskCreateRequest
from memtrace_api.store import TaskStore

TEST_SESSION_SECRET = "test_session_secret_01234567890123456789"
TASK_BODY: dict[str, Any] = {
    "task_text": "请解释 Python 列表越界并给出调试步骤",
    "memory_mode": "on",
    "current_constraints": {
        "response_policy": "guided_hint",
        "urgency": "normal",
        "memory_disabled": False,
        "source": "ui",
    },
}


def test_eight_concurrent_event_allocations_are_unique_and_contiguous(
    tmp_db_url: str,
) -> None:
    engine = create_db_engine(tmp_db_url)
    factory = create_session_factory(engine)
    request = TaskCreateRequest.model_validate(TASK_BODY)
    analysis = analyze_task(request)
    task_id = new_prefixed_ulid("task")
    run_id = new_prefixed_ulid("run")

    with session_scope(factory) as session:
        user = UserRepository(session).ensure_demo_users()["blank_demo"]
        user_ctx = UserContext(user_id=user.id, demo_alias=user.demo_alias)
        TaskRepository(user_ctx, session).create_task(
            task_id=task_id,
            run_id=run_id,
            request=request,
            detected_domain=analysis.fingerprint.domain,
            provider_mode=ProviderMode.MOCK,
            model="mock-g0",
        )

    def allocate(_: int) -> int:
        with session_scope(factory) as session:
            return TaskRepository(user_ctx, session).allocate_next_event_seq(task_id)

    with ThreadPoolExecutor(max_workers=8) as executor:
        allocated = list(executor.map(allocate, range(8)))

    assert sorted(allocated) == list(range(2, 10))
    with session_scope(factory) as session:
        next_value = session.execute(
            select(TaskModel.next_event_seq).where(TaskModel.id == task_id)
        ).scalar_one()
    assert next_value == 10
    engine.dispose()


def test_capacity_rejection_leaves_no_durable_ghost_rows(
    tmp_path: Path,
    tmp_db_url: str,
) -> None:
    store = TaskStore(
        max_tasks=1,
        max_subscribers_per_task=8,
        subscriber_queue_size=64,
    )
    request = TaskCreateRequest.model_validate(TASK_BODY)
    asyncio.run(
        store.create(
            request=request,
            analysis=analyze_task(request),
            request_id=new_prefixed_ulid("req"),
            provider_mode=ProviderMode.MOCK,
        )
    )
    settings = _settings(tmp_path, tmp_db_url)

    with TestClient(create_app(settings, store=store)) as client:
        login = client.post("/api/v1/session/demo", json={"demo_alias": "blank_demo"})
        assert login.status_code == 200
        before = _durable_counts(client)
        response = client.post(
            "/api/v1/tasks",
            json=TASK_BODY,
            headers={"Idempotency-Key": "capacity-rejection-key-0001"},
        )
        after = _durable_counts(client)

    assert response.status_code == 503
    assert after == before
    assert asyncio.run(store.capacity_counts()) == (1, 0)


def test_concurrent_same_idempotency_key_creates_one_durable_task(
    tmp_path: Path,
    tmp_db_url: str,
) -> None:
    store = TaskStore(
        max_tasks=100,
        max_subscribers_per_task=8,
        subscriber_queue_size=64,
    )
    app = create_app(_settings(tmp_path, tmp_db_url), store=store)
    barrier = Barrier(8)

    with TestClient(app) as client:
        login = client.post("/api/v1/session/demo", json={"demo_alias": "blank_demo"})
        assert login.status_code == 200
        cookie = client.cookies.get("memtrace_demo_session")
        assert cookie is not None

        def submit(_: int) -> tuple[int, dict[str, Any]]:
            barrier.wait()
            response = client.post(
                "/api/v1/tasks",
                json=TASK_BODY,
                headers={
                    "Cookie": f"memtrace_demo_session={cookie}",
                    "Idempotency-Key": "concurrent-create-key-0001",
                },
            )
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(executor.map(submit, range(8)))

        assert {status for status, _ in responses} == {202}
        assert len({body["task_id"] for _, body in responses}) == 1
        assert len({body["run_id"] for _, body in responses}) == 1
        counts = _durable_counts(client)

    assert counts["tasks"] == 1
    assert counts["agent_runs"] == 1
    assert counts["idempotency_keys"] == 1
    assert asyncio.run(store.capacity_counts()) == (1, 0)


def _settings(tmp_path: Path, db_url: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        mock_mode=True,
        mock_chunk_delay_ms=25,
        memtrace_data_dir=tmp_path / "data",
        memtrace_database_url=db_url,
        session_secret=TEST_SESSION_SECRET,
    )


def _durable_counts(client: TestClient) -> dict[str, int]:
    models = {
        "tasks": TaskModel,
        "agent_runs": AgentRunModel,
        "messages": MessageModel,
        "event_log": EventLogModel,
        "idempotency_keys": IdempotencyKeyModel,
    }
    with session_scope(client.app.state.db_session_factory) as session:
        return {
            name: session.execute(select(func.count()).select_from(model)).scalar_one()
            for name, model in models.items()
        }
