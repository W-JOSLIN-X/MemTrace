"""Owner-side G2 runtime tests against the real FastAPI lifespan and SQLite."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from conftest import TEST_SESSION_SECRET, migrate_database
from memtrace_api.compiler import MockStructuredProvider, ProviderFailure, StructuredProvider
from memtrace_api.config import Settings
from memtrace_api.db_models import MemoryCardModel
from memtrace_api.events import EventType
from memtrace_api.main import create_app
from memtrace_api.repositories import TaskRepository, UserRepository
from memtrace_api.schemas import utc_now

TASK_REQUEST: dict[str, Any] = {
    "task_text": "请解释 Python 递归调试时如何观察终止条件。",
    "memory_mode": "on",
    "current_constraints": {
        "response_policy": "guided_hint",
        "urgency": "normal",
        "memory_disabled": False,
        "source": "ui",
    },
}


def _client(
    tmp_path: Path,
    *,
    alias: str = "blank_demo",
    memory_provider: StructuredProvider | None = None,
) -> TestClient:
    db_url = f"sqlite:///{(tmp_path / 'g2.sqlite3').as_posix()}"
    migrate_database(db_url)
    settings = Settings(
        _env_file=None,
        app_env="test",
        mock_mode=True,
        mock_chunk_delay_ms=0,
        memtrace_data_dir=tmp_path / "data",
        memtrace_database_url=db_url,
        session_secret=TEST_SESSION_SECRET,
    )
    client = TestClient(create_app(settings, memory_provider=memory_provider))
    client.__enter__()
    login = client.post("/api/v1/session/demo", json={"demo_alias": alias})
    assert login.status_code == 200, login.text
    return client


def _task_to_terminal(client: TestClient, *, key: str) -> dict[str, Any]:
    created = client.post(
        "/api/v1/tasks",
        json=TASK_REQUEST,
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 202, created.text
    payload = created.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/v1/tasks/{payload['task_id']}")
        assert snapshot.status_code == 200, snapshot.text
        if snapshot.json()["terminal"]:
            return payload
        time.sleep(0.02)
    raise AssertionError("task did not become terminal")


def _feedback_to_terminal_job(
    client: TestClient,
    task_id: str,
    feedback: dict[str, Any],
    *,
    key: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/tasks/{task_id}/feedback",
        json=feedback,
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["memory_job_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/memory-jobs/{job_id}")
        assert job.status_code == 200, job.text
        if job.json()["status"] in {"completed", "failed"}:
            return job.json()
        time.sleep(0.02)
    raise AssertionError("memory job did not become terminal")


def test_lifespan_worker_creates_candidate_and_accepts_v1(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        task = _task_to_terminal(client, key="g2-task-durable-0001")
        job = _feedback_to_terminal_job(
            client,
            task["task_id"],
            {"explicit_text": "以后调试递归时，先提示我检查终止条件，再给完整答案。"},
            key="g2-feedback-durable-0001",
        )
        assert job["status"] == "completed"
        assert job["stage"] == "done"
        assert job["attempt"] == 1
        assert job["disposition"] == "candidate_created"
        assert len(job["candidate_ids"]) == 1
        assert job["error_code"] is None
        assert job["retryable"] is False

        memory_id = job["candidate_ids"][0]
        detail = client.get(f"/api/v1/memories/{memory_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["card"]["status"] == "candidate"
        assert detail.json()["card"]["current_version_id"] is None
        assert len(detail.json()["evidence"]) == 1

        resolved = client.post(
            f"/api/v1/memory-candidates/{memory_id}/resolve",
            json={"action": "accept"},
            headers={"Idempotency-Key": "g2-resolve-accept-0001"},
        )
        assert resolved.status_code == 200, resolved.text
        body = resolved.json()
        assert body["new_status"] == "active"
        assert body["memory_version_id"] is not None
        assert body["card"]["version"] == 1
        assert body["card"]["current_version_id"] == body["memory_version_id"]

        replay = client.post(
            f"/api/v1/memory-candidates/{memory_id}/resolve",
            json={"action": "accept", "patch": None},
            headers={"Idempotency-Key": "g2-resolve-accept-0001"},
        )
        assert replay.status_code == 200
        assert replay.json() == body

        conflict = client.post(
            f"/api/v1/memory-candidates/{memory_id}/resolve",
            json={"action": "reject"},
            headers={"Idempotency-Key": "g2-resolve-accept-0001"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

        duplicate = client.post(
            f"/api/v1/memory-candidates/{memory_id}/resolve",
            json={"action": "accept"},
            headers={"Idempotency-Key": "g2-resolve-accept-0002"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "MEMORY_ALREADY_RESOLVED"
    finally:
        client.__exit__(None, None, None)


class _FailOnceProvider(StructuredProvider):
    name = "fail-once"
    mode = "mock"

    def __init__(self) -> None:
        self.calls = 0
        self.delegate = MockStructuredProvider()

    async def complete_json(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        simulation: str | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise ProviderFailure("MEMORY_PROVIDER_ERROR", retryable=True)
        return await self.delegate.complete_json(
            prompt,
            output_schema,
            simulation=simulation,
        )


class _InvalidThenValidProvider(StructuredProvider):
    name = "invalid-then-valid"
    mode = "mock"

    def __init__(self, *, always_invalid: bool = False) -> None:
        self.calls = 0
        self.always_invalid = always_invalid
        self.delegate = MockStructuredProvider()

    async def complete_json(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        simulation: str | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        if self.always_invalid or self.calls == 1:
            return {"schema_version": "1.0", "unexpected": True}
        return await self.delegate.complete_json(
            prompt,
            output_schema,
            simulation=simulation,
        )


class _ThreeCandidateProvider(StructuredProvider):
    name = "three-candidates"
    mode = "mock"

    def __init__(self) -> None:
        self.delegate = MockStructuredProvider()

    async def complete_json(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        simulation: str | None = None,
    ) -> dict[str, Any]:
        body = await self.delegate.complete_json(
            prompt,
            output_schema,
            simulation=simulation,
        )
        candidate = body["candidates"][0]
        body["candidates"] = [
            {**candidate, "title": f"候选记忆规则编号{index}"} for index in range(1, 4)
        ]
        return body


def test_failed_job_retry_requeues_and_increments_attempt(tmp_path: Path) -> None:
    provider = _FailOnceProvider()
    client = _client(tmp_path, memory_provider=provider)
    try:
        task = _task_to_terminal(client, key="g2-task-retry-0001")
        failed = _feedback_to_terminal_job(
            client,
            task["task_id"],
            {"explicit_text": "以后调试时始终先给诊断步骤，再给完整修复。"},
            key="g2-feedback-retry-0001",
        )
        assert failed["status"] == "failed"
        assert failed["attempt"] == 1
        assert failed["error_code"] == "MEMORY_PROVIDER_ERROR"
        assert failed["retryable"] is True

        retry = client.post(
            f"/api/v1/memory-jobs/{failed['memory_job_id']}/retry",
            headers={"Idempotency-Key": "g2-job-retry-key-0001"},
        )
        assert retry.status_code == 202, retry.text
        accepted = retry.json()
        assert accepted["status"] == "pending"
        assert accepted["stage"] == "queued"
        assert accepted["attempt"] == 1
        assert accepted["disposition"] is None
        assert accepted["error_code"] is None
        assert accepted["retryable"] is False

        replay = client.post(
            f"/api/v1/memory-jobs/{failed['memory_job_id']}/retry",
            headers={"Idempotency-Key": "g2-job-retry-key-0001"},
        )
        assert replay.status_code == 202
        assert replay.json() == accepted

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f"/api/v1/memory-jobs/{failed['memory_job_id']}")
            assert current.status_code == 200
            if current.json()["status"] == "completed":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("retried memory job did not complete")
        assert current.json()["attempt"] == 2
        assert current.json()["candidate_ids"]

        invalid_retry = client.post(
            f"/api/v1/memory-jobs/{failed['memory_job_id']}/retry",
            headers={"Idempotency-Key": "g2-job-retry-key-0002"},
        )
        assert invalid_retry.status_code == 409
        assert invalid_retry.json()["error"]["code"] == "MEMORY_JOB_NOT_RETRYABLE"
    finally:
        client.__exit__(None, None, None)


def test_schema_repair_succeeds_once_and_failure_is_controlled(tmp_path: Path) -> None:
    success_dir = tmp_path / "repair-success"
    success_dir.mkdir()
    success_provider = _InvalidThenValidProvider()
    success = _client(success_dir, memory_provider=success_provider)
    try:
        task = _task_to_terminal(success, key="g2-task-repair-success-0001")
        job = _feedback_to_terminal_job(
            success,
            task["task_id"],
            {"explicit_text": "以后调试时必须先复现，再给完整修改。"},
            key="g2-feedback-repair-success-0001",
        )
        assert job["status"] == "completed"
        assert job["candidate_ids"]
        assert success_provider.calls == 2
    finally:
        success.__exit__(None, None, None)

    failure_dir = tmp_path / "repair-failure"
    failure_dir.mkdir()
    failure_provider = _InvalidThenValidProvider(always_invalid=True)
    failure = _client(failure_dir, memory_provider=failure_provider)
    try:
        task = _task_to_terminal(failure, key="g2-task-repair-failure-0001")
        job = _feedback_to_terminal_job(
            failure,
            task["task_id"],
            {"explicit_text": "以后调试时必须先复现，再给完整修改。"},
            key="g2-feedback-repair-failure-0001",
        )
        assert job["status"] == "failed"
        assert job["error_code"] == "MEMORY_REPAIR_FAILED"
        assert job["retryable"] is False
        assert job["candidate_ids"] == []
        assert failure_provider.calls == 2
    finally:
        failure.__exit__(None, None, None)


def test_worker_persists_three_candidates_in_stable_ordinal_order(tmp_path: Path) -> None:
    provider = _ThreeCandidateProvider()
    client = _client(tmp_path, memory_provider=provider)
    try:
        task = _task_to_terminal(client, key="g2-task-three-cards-0001")
        job = _feedback_to_terminal_job(
            client,
            task["task_id"],
            {"explicit_text": "以后调试时始终先验证输入，再说明原因，最后给修改。"},
            key="g2-feedback-three-cards-0001",
        )
        assert job["status"] == "completed"
        assert len(job["candidate_ids"]) == 3
        titles = [
            client.get(f"/api/v1/memories/{memory_id}").json()["card"]["title"]
            for memory_id in job["candidate_ids"]
        ]
        assert titles == ["候选记忆规则编号1", "候选记忆规则编号2", "候选记忆规则编号3"]
    finally:
        client.__exit__(None, None, None)


def test_concurrent_resolve_has_one_winner_and_same_key_replays(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        task = _task_to_terminal(client, key="g2-task-resolve-race-0001")
        first_job = _feedback_to_terminal_job(
            client,
            task["task_id"],
            {"explicit_text": "以后调试时必须先验证失败现象，再给修改方案。"},
            key="g2-feedback-resolve-race-0001",
        )
        first_memory_id = first_job["candidate_ids"][0]

        def resolve_with_key(key: str):
            return client.post(
                f"/api/v1/memory-candidates/{first_memory_id}/resolve",
                json={"action": "accept"},
                headers={"Idempotency-Key": key},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    resolve_with_key,
                    ["g2-resolve-race-key-0001", "g2-resolve-race-key-0002"],
                )
            )
        assert sorted(response.status_code for response in responses) == [200, 409]
        detail = client.get(f"/api/v1/memories/{first_memory_id}").json()
        assert detail["card"]["status"] == "active"
        assert len(detail["versions"]) == 1

        second_job = _feedback_to_terminal_job(
            client,
            task["task_id"],
            {"explicit_text": "以后调试时必须先检查边界输入，再给修改方案。"},
            key="g2-feedback-resolve-race-0002",
        )
        second_memory_id = second_job["candidate_ids"][0]

        def resolve_same_key(_: int):
            return client.post(
                f"/api/v1/memory-candidates/{second_memory_id}/resolve",
                json={"action": "reject"},
                headers={"Idempotency-Key": "g2-resolve-same-key-0001"},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            replays = list(pool.map(resolve_same_key, range(2)))
        assert [response.status_code for response in replays] == [200, 200]
        assert replays[0].json() == replays[1].json()
        assert client.get(f"/api/v1/memories/{second_memory_id}").json()["versions"] == []
    finally:
        client.__exit__(None, None, None)


def test_memory_list_uses_descending_opaque_cursor_and_explicit_nulls(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        factory = client.app.state.db_session_factory
        expected_ids: set[str] = set()
        with factory() as session:
            owner = UserRepository(session).get_by_alias("blank_demo")
            assert owner is not None
            now = utc_now()
            for index in range(51):
                memory_id = f"mem_01J00000000000000000000{index:03d}"
                expected_ids.add(memory_id)
                session.add(
                    MemoryCardModel(
                        id=memory_id,
                        owner_id=owner.id,
                        memory_job_id=None,
                        current_version_id=None,
                        status="candidate",
                        kind="preference",
                        source_type="explicit_feedback",
                        save_preselected=False,
                        rejection_reason=None,
                        title=f"分页候选记忆{index:02d}",
                        rule="在分页测试的后续相似任务中，应保持稳定的倒序游标返回语义。",
                        avoid="",
                        trigger_text="分页测试",
                        scope_level="session",
                        domain="other",
                        task_type=None,
                        artifact_type=None,
                        audience=None,
                        project_key=None,
                        scope_json='{"level":"session","domain":"other"}',
                        exceptions_json="[]",
                        source_trust=1.0,
                        rule_confidence=None,
                        scope_confidence=None,
                        evidence_count=0,
                        version=0,
                        valid_from=None,
                        valid_to=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.commit()

        first = client.get("/api/v1/memories?status=candidate")
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert len(first_body["items"]) == 50
        assert first_body["next_cursor"] == first_body["items"][-1]["memory_id"]
        assert first_body["items"] == sorted(
            first_body["items"],
            key=lambda item: item["memory_id"],
            reverse=True,
        )
        assert first_body["items"][0]["current_version_id"] is None
        assert first_body["items"][0]["rule_confidence"] is None
        assert first_body["items"][0]["scope_confidence"] is None

        second = client.get(
            "/api/v1/memories",
            params={"status": "candidate", "cursor": first_body["next_cursor"]},
        )
        assert second.status_code == 200
        second_body = second.json()
        assert len(second_body["items"]) == 1
        assert second_body["next_cursor"] is None
        returned = {item["memory_id"] for item in first_body["items"] + second_body["items"]}
        assert returned == expected_ids

        invalid = client.get("/api/v1/memories?cursor=not-a-memory-id")
        assert invalid.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_one_shot_finishes_without_long_term_candidate(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        task = _task_to_terminal(client, key="g2-task-oneshot-0001")
        job = _feedback_to_terminal_job(
            client,
            task["task_id"],
            {"explicit_text": "这次赶时间，直接给完整答案就行。"},
            key="g2-feedback-oneshot-0001",
        )
        assert job["status"] == "completed"
        assert job["disposition"] == "episode_only"
        assert job["candidate_ids"] == []
        listed = client.get("/api/v1/memories")
        assert listed.status_code == 200
        assert listed.json() == {
            "request_id": listed.json()["request_id"],
            "items": [],
            "next_cursor": None,
        }
    finally:
        client.__exit__(None, None, None)


def test_edit_reject_and_one_shot_resolve_semantics(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        task = _task_to_terminal(client, key="g2-task-actions-0001")
        cases = [
            (
                "edit_accept",
                {
                    "action": "edit_accept",
                    "patch": {"title": "编辑确认后的偏好", "avoid": ""},
                },
                "active",
                "candidate_created",
                True,
                None,
            ),
            (
                "reject",
                {"action": "reject"},
                "rejected",
                "no_memory",
                False,
                "user_rejected",
            ),
            (
                "one_shot",
                {"action": "one_shot"},
                "rejected",
                "episode_only",
                False,
                "episode_only",
            ),
        ]
        for index, (
            action,
            resolve_body,
            expected_status,
            disposition,
            has_version,
            rejection_reason,
        ) in enumerate(
            cases,
            start=1,
        ):
            job = _feedback_to_terminal_job(
                client,
                task["task_id"],
                {"explicit_text": f"以后处理第{index}类调试任务时，始终先解释原因再给答案。"},
                key=f"g2-feedback-action-000{index}",
            )
            memory_id = job["candidate_ids"][0]
            response = client.post(
                f"/api/v1/memory-candidates/{memory_id}/resolve",
                json=resolve_body,
                headers={"Idempotency-Key": f"g2-resolve-{action}-0001"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["action"] == action
            assert body["new_status"] == expected_status
            assert body["disposition"] == disposition
            assert (body["memory_version_id"] is not None) is has_version
            assert body["card"]["status"] == expected_status
            assert body["card"]["rejection_reason"] == rejection_reason
            if action == "edit_accept":
                assert body["card"]["title"] == "编辑确认后的偏好"
                assert body["card"]["avoid"] == ""
            detail = client.get(f"/api/v1/memories/{memory_id}").json()
            assert detail["card"]["rejection_reason"] == rejection_reason
            assert len(detail["versions"]) == (1 if has_version else 0)
    finally:
        client.__exit__(None, None, None)


def test_day3_events_replay_after_historical_stream_done(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        task = _task_to_terminal(client, key="g2-task-catchup-0001")
        job = _feedback_to_terminal_job(
            client,
            task["task_id"],
            {"explicit_text": "以后调试时必须先说明失败原因，再给修改方案。"},
            key="g2-feedback-catchup-0001",
        )
        assert job["status"] == "completed"
        with client.stream(
            "GET",
            f"/api/v1/tasks/{task['task_id']}/events?after_event_seq=0",
        ) as response:
            assert response.status_code == 200
            raw = "".join(response.iter_text()).replace("\r\n", "\n")
        event_types = [
            line.removeprefix("event: ") for line in raw.splitlines() if line.startswith("event: ")
        ]
        stream_done_index = event_types.index("stream.done")
        assert "feedback.recorded" in event_types[stream_done_index + 1 :]
        assert "memory.extraction.stage" in event_types[stream_done_index + 1 :]
        assert "memory.candidate.created" in event_types[stream_done_index + 1 :]
    finally:
        client.__exit__(None, None, None)


def test_cross_owner_job_card_resolve_and_sse_are_404(tmp_path: Path) -> None:
    owner = _client(tmp_path, alias="blank_demo")
    other: TestClient | None = None
    try:
        task = _task_to_terminal(owner, key="g2-task-owner-0001")
        job = _feedback_to_terminal_job(
            owner,
            task["task_id"],
            {"explicit_text": "以后遇到递归问题时，先提示我检查终止条件。"},
            key="g2-feedback-owner-0001",
        )
        memory_id = job["candidate_ids"][0]
        other = _client(tmp_path, alias="seeded_demo")

        assert other.get(f"/api/v1/memory-jobs/{job['memory_job_id']}").status_code == 404
        assert other.get(f"/api/v1/memories/{memory_id}").status_code == 404
        resolve = other.post(
            f"/api/v1/memory-candidates/{memory_id}/resolve",
            json={"action": "reject"},
            headers={"Idempotency-Key": "g2-cross-owner-resolve-0001"},
        )
        assert resolve.status_code == 404
        assert resolve.json()["error"]["code"] == "MEMORY_NOT_FOUND"
        assert other.get(f"/api/v1/tasks/{task['task_id']}/events").status_code == 404
    finally:
        if other is not None:
            other.__exit__(None, None, None)
        owner.__exit__(None, None, None)


def test_resolve_rolls_back_card_version_event_and_idempotency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    try:
        task = _task_to_terminal(client, key="g2-task-resolve-rollback-0001")
        job = _feedback_to_terminal_job(
            client,
            task["task_id"],
            {"explicit_text": "以后调试时必须先复现问题，再给修复建议。"},
            key="g2-feedback-resolve-rollback-0001",
        )
        memory_id = job["candidate_ids"][0]
        original = TaskRepository.append_event

        def fail_admission_event(self, **kwargs):
            if kwargs["event_type"] == EventType.MEMORY_ADMISSION_RESOLVED.value:
                raise RuntimeError("forced admission event failure")
            return original(self, **kwargs)

        monkeypatch.setattr(TaskRepository, "append_event", fail_admission_event)
        failed = client.post(
            f"/api/v1/memory-candidates/{memory_id}/resolve",
            json={"action": "accept"},
            headers={"Idempotency-Key": "g2-resolve-rollback-0001"},
        )
        assert failed.status_code == 500
        detail = client.get(f"/api/v1/memories/{memory_id}").json()
        assert detail["card"]["status"] == "candidate"
        assert detail["card"]["version"] == 0
        assert detail["versions"] == []

        monkeypatch.setattr(TaskRepository, "append_event", original)
        retried = client.post(
            f"/api/v1/memory-candidates/{memory_id}/resolve",
            json={"action": "accept"},
            headers={"Idempotency-Key": "g2-resolve-rollback-0001"},
        )
        assert retried.status_code == 200, retried.text
    finally:
        client.__exit__(None, None, None)


def test_candidate_event_failure_rolls_back_candidate_and_records_sanitized_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    try:
        task = _task_to_terminal(client, key="g2-task-worker-rollback-0001")
        original = TaskRepository.append_event

        def fail_candidate_event(self, **kwargs):
            if kwargs["event_type"] == EventType.MEMORY_CANDIDATE_CREATED.value:
                raise RuntimeError("forced candidate event failure")
            return original(self, **kwargs)

        monkeypatch.setattr(TaskRepository, "append_event", fail_candidate_event)
        job = _feedback_to_terminal_job(
            client,
            task["task_id"],
            {"explicit_text": "以后调试时始终先检查输入边界，再给最终修复。"},
            key="g2-feedback-worker-rollback-0001",
        )
        assert job["status"] == "failed"
        assert job["candidate_ids"] == []
        assert job["error_code"] == "MEMORY_SCHEMA_INVALID"
        assert client.get("/api/v1/memories").json()["items"] == []

        with client.stream(
            "GET",
            f"/api/v1/tasks/{task['task_id']}/events?after_event_seq=0",
        ) as response:
            raw = "".join(response.iter_text())
        assert "memory.job.failed" in raw
        assert "以后调试时始终先检查输入边界" not in raw
        assert "forced candidate event failure" not in raw
    finally:
        client.__exit__(None, None, None)
