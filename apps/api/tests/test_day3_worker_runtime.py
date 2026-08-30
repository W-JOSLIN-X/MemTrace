"""Worker claim, restart recovery, and persistent-event concurrency tests."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from memtrace_api.config import Settings
from memtrace_api.db_models import EventLogModel, FeedbackEventModel, MemoryJobModel
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.main import create_app
from memtrace_api.repositories import UserRepository
from memtrace_api.schemas import MemoryScope, utc_now
from memtrace_api.store import TaskStore
from memtrace_api.worker import MemoryJobWorker
from test_day3_owner_g2 import _client, _task_to_terminal


def _seed_jobs(
    client: TestClient,
    *,
    task_id: str,
    run_id: str,
    count: int,
) -> list[str]:
    factory = client.app.state.db_session_factory
    job_ids: list[str] = []
    with factory() as session:
        owner = UserRepository(session).get_by_alias("blank_demo")
        assert owner is not None
        now = utc_now()
        for index in range(count):
            feedback_id = new_prefixed_ulid("feedback")
            job_id = new_prefixed_ulid("job")
            job_ids.append(job_id)
            session.add_all(
                [
                    FeedbackEventModel(
                        id=feedback_id,
                        owner_id=owner.id,
                        task_id=task_id,
                        run_id=run_id,
                        feedback_type="explicit_text",
                        explicit_text=(f"以后处理并发测试 {index} 时，始终先验证原子领取再继续。"),
                        edited_output=None,
                        rating=None,
                        accepted=None,
                        created_at=now,
                    ),
                    MemoryJobModel(
                        id=job_id,
                        owner_id=owner.id,
                        job_type="extract_feedback",
                        feedback_id=feedback_id,
                        status="pending",
                        stage="queued",
                        attempt=0,
                        last_error_code=None,
                        retryable=False,
                        disposition=None,
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
        session.commit()
    return job_ids


def _store() -> TaskStore:
    return TaskStore(
        max_tasks=100,
        max_subscribers_per_task=8,
        subscriber_queue_size=64,
    )


def test_memory_scope_normalizes_provider_concepts_without_g2_regression() -> None:
    scope = MemoryScope.model_validate(
        {
            "level": "task_family",
            "domain": "programming_learning",
            "task_type": "debugging_guidance",
            "artifact_type": "source_code",
            "audience": "beginner",
            "project_key": None,
            "language": "python",
            "framework": None,
            "concepts": ["Loops", "debugging", "loops"],
        }
    )
    assert scope.concepts == ["debugging", "loops"]


def test_real_provider_mode_keeps_legacy_g2_worker_available(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        mock_mode=False,
        llm_api_key="unit-test-placeholder",
        memtrace_data_dir=tmp_path / "data",
        memtrace_database_url=f"sqlite:///{(tmp_path / 'stale.sqlite3').as_posix()}",
    )
    app = create_app(settings)

    with TestClient(app):
        assert app.state.memory_worker is not None
        assert app.state.memory_worker._provider.mode == "real"


def test_two_workers_atomically_claim_eight_jobs_once(tmp_path) -> None:
    client = _client(tmp_path)
    try:
        task = _task_to_terminal(client, key="g2-task-claim-race-0001")
        snapshot = client.get(f"/api/v1/tasks/{task['task_id']}").json()
        factory = client.app.state.db_session_factory
        settings = client.app.state.settings
    finally:
        client.__exit__(None, None, None)

    # Seed only after the app-owned worker has stopped. Seeding while the
    # TestClient is alive races that background worker against the eight
    # explicit claim calls below and makes this atomicity test nondeterministic.
    job_ids = _seed_jobs(
        client,
        task_id=task["task_id"],
        run_id=snapshot["run_id"],
        count=8,
    )

    workers = [
        MemoryJobWorker(factory, settings, _store()),
        MemoryJobWorker(factory, settings, _store()),
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(
            pool.map(
                lambda index: workers[index % 2]._claim_next_job(),
                range(8),
            )
        )
    assert all(claim is not None for claim in claims)
    claimed_ids = [claim.job_id for claim in claims if claim is not None]
    assert len(claimed_ids) == len(set(claimed_ids)) == 8
    assert set(claimed_ids) == set(job_ids)
    assert workers[0]._claim_next_job() is None

    with factory() as session:
        rows = list(
            session.execute(select(MemoryJobModel).where(MemoryJobModel.id.in_(job_ids))).scalars()
        )
        assert {row.status for row in rows} == {"running"}
        assert {row.attempt for row in rows} == {1}


def test_restart_interrupts_running_and_processes_pending(tmp_path) -> None:
    client = _client(tmp_path)
    try:
        task = _task_to_terminal(client, key="g2-task-restart-worker-0001")
        snapshot = client.get(f"/api/v1/tasks/{task['task_id']}").json()
        job_ids = _seed_jobs(
            client,
            task_id=task["task_id"],
            run_id=snapshot["run_id"],
            count=2,
        )
        factory = client.app.state.db_session_factory
        settings = client.app.state.settings
    finally:
        client.__exit__(None, None, None)

    orphaned_worker = MemoryJobWorker(factory, settings, _store())
    claimed = orphaned_worker._claim_next_job()
    assert claimed is not None
    claimed_id = claimed.job_id
    pending_id = next(job_id for job_id in job_ids if job_id != claimed_id)

    restarted = TestClient(create_app(settings))
    with restarted:
        login = restarted.post(
            "/api/v1/session/demo",
            json={"demo_alias": "blank_demo"},
        )
        assert login.status_code == 200
        interrupted = restarted.get(f"/api/v1/memory-jobs/{claimed_id}")
        assert interrupted.status_code == 200
        interrupted_body = interrupted.json()
        assert interrupted_body["status"] == "failed"
        assert interrupted_body["stage"] == "failed"
        assert interrupted_body["error_code"] == "MEMORY_JOB_INTERRUPTED"
        assert interrupted_body["retryable"] is True

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pending = restarted.get(f"/api/v1/memory-jobs/{pending_id}")
            assert pending.status_code == 200
            if pending.json()["status"] == "completed":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("pending job was not resumed after restart")
        assert pending.json()["attempt"] == 1
        assert pending.json()["candidate_ids"]

    with factory() as session:
        events = list(
            session.execute(
                select(EventLogModel)
                .where(EventLogModel.stream_id == task["task_id"])
                .order_by(EventLogModel.seq.asc())
            ).scalars()
        )
    sequences = [event.seq for event in events]
    assert sequences == list(range(1, max(sequences) + 1))
    interrupted_events = [event for event in events if event.event_type == "memory.job.failed"]
    assert len(interrupted_events) == 1
    metadata: dict[str, Any] = json.loads(interrupted_events[0].metadata_json)
    assert metadata == {
        "memory_job_id": claimed_id,
        "stage": "failed",
        "error_code": "MEMORY_JOB_INTERRUPTED",
        "retryable": True,
    }
