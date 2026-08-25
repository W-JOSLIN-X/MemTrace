"""Owner-side G3 API and orchestrator tests against migrated SQLite."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from conftest import TEST_SESSION_SECRET, migrate_database
from memtrace_api.config import Settings
from memtrace_api.main import create_app

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


def _client(tmp_path: Path) -> TestClient:
    db_url = f"sqlite:///{(tmp_path / 'g3.sqlite3').as_posix()}"
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
    client = TestClient(create_app(settings))
    client.__enter__()
    assert client.post("/api/v1/session/demo", json={"demo_alias": "blank_demo"}).status_code == 200
    return client


def _terminal_task(
    client: TestClient, key: str, request: dict[str, Any] | None = None
) -> dict[str, Any]:
    accepted = client.post(
        "/api/v1/tasks",
        json=request or TASK_REQUEST,
        headers={"Idempotency-Key": key},
    )
    assert accepted.status_code == 202, accepted.text
    task_id = accepted.json()["task_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/v1/tasks/{task_id}")
        assert snapshot.status_code == 200, snapshot.text
        if snapshot.json()["terminal"]:
            return snapshot.json()
        time.sleep(0.02)
    raise AssertionError("task did not become terminal")


def _active_memory(client: TestClient) -> dict[str, Any]:
    source = _terminal_task(client, "g3-source-task-0001")
    feedback = client.post(
        f"/api/v1/tasks/{source['task_id']}/feedback",
        json={"explicit_text": "以后解释 Python 递归调试时，先提醒我检查终止条件，再给完整答案。"},
        headers={"Idempotency-Key": "g3-source-feedback-0001"},
    )
    assert feedback.status_code == 202, feedback.text
    job_id = feedback.json()["memory_job_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/memory-jobs/{job_id}").json()
        if job["status"] == "completed":
            memory_id = job["candidate_ids"][0]
            resolved = client.post(
                f"/api/v1/memory-candidates/{memory_id}/resolve",
                json={"action": "accept"},
                headers={"Idempotency-Key": "g3-source-accept-0001"},
            )
            assert resolved.status_code == 200, resolved.text
            card = resolved.json()["card"]
            edited = client.patch(
                f"/api/v1/memories/{memory_id}",
                json={
                    "expected_current_version_id": card["current_version_id"],
                    "patch": {"rule": source["fingerprint"]["semantic_query"]},
                },
                headers={"Idempotency-Key": "g3-source-edit-0001"},
            )
            assert edited.status_code == 200, edited.text
            return edited.json()["card"]
        time.sleep(0.02)
    raise AssertionError("memory job did not become terminal")


def test_g3_retrieval_injection_lifecycle_and_owner_scoped_routes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        card = _active_memory(client)
        first = _terminal_task(client, "g3-retrieval-task-0001")
        assert first["run_status"] == "succeeded", first["error"]
        trace = first["retrieval_trace"]
        assert trace["candidate_count"] == 1
        assert trace["retrieved_count"] == 1
        assert trace["selected_count"] == 1, trace["decisions"][0]["final_score"]
        assert trace["injected_count"] == 1
        assert trace["provider_prompt_tokens_actual"] is None
        assert trace["memory_tokens_estimated"] <= 300
        assert trace["decisions"][0]["reason_codes"] == ["selected_above_threshold"]
        assert card["rule"] in first["final_message"]["content"]
        assert first["public_plan"]["memory_summary"].startswith("已选择并注入 1 张")
        assert len(first["memory_usages"]) == 1
        assert first["memory_usages"][0]["verification_status"] == "applied"

        trace_response = client.get(f"/api/v1/tasks/{first['task_id']}/retrieval-trace")
        usages_response = client.get(f"/api/v1/tasks/{first['task_id']}/memory-usages")
        assert trace_response.status_code == 200
        assert trace_response.json()["retrieval_trace_id"] == trace["retrieval_trace_id"]
        assert usages_response.status_code == 200
        assert usages_response.json()["items"][0]["memory_id"] == card["memory_id"]

        effect_path = f"/api/v1/tasks/{first['task_id']}/memory-usages/{card['memory_id']}/feedback"
        effect = client.post(
            effect_path,
            json={"effect": "helpful"},
            headers={"Idempotency-Key": "g3-effect-0001"},
        )
        assert effect.status_code == 200, effect.text
        assert effect.json()["user_effect"] == "helpful"
        replay = client.post(
            effect_path,
            json={"effect": "helpful"},
            headers={"Idempotency-Key": "g3-effect-0001"},
        )
        assert replay.status_code == 200
        conflict = client.post(
            effect_path,
            json={"effect": "harmful"},
            headers={"Idempotency-Key": "g3-effect-0001"},
        )
        assert conflict.status_code == 409

        assert (
            client.post("/api/v1/session/demo", json={"demo_alias": "seeded_demo"}).status_code
            == 200
        )
        hidden_paths = (
            f"/api/v1/tasks/{first['task_id']}",
            f"/api/v1/tasks/{first['task_id']}/retrieval-trace",
            f"/api/v1/tasks/{first['task_id']}/memory-usages",
            f"/api/v1/tasks/{first['task_id']}/events",
            f"/api/v1/memories/{card['memory_id']}",
            f"/api/v1/memories/{card['memory_id']}/versions",
            f"/api/v1/memories/{card['memory_id']}/usages",
        )
        for path in hidden_paths:
            assert client.get(path).status_code == 404, path
        assert (
            client.post("/api/v1/session/demo", json={"demo_alias": "blank_demo"}).status_code
            == 200
        )

        pause = client.post(
            f"/api/v1/memories/{card['memory_id']}/pause",
            json={"expected_current_version_id": card["current_version_id"]},
            headers={"Idempotency-Key": "g3-pause-0001"},
        )
        assert pause.status_code == 200, pause.text
        assert pause.json()["card"]["status"] == "paused"
        paused_task = _terminal_task(client, "g3-paused-task-0001")
        assert paused_task["retrieval_trace"]["selected_count"] == 0

        resume = client.post(
            f"/api/v1/memories/{card['memory_id']}/resume",
            json={"expected_current_version_id": card["current_version_id"]},
            headers={"Idempotency-Key": "g3-resume-0001"},
        )
        assert resume.status_code == 200, resume.text
        resumed_task = _terminal_task(client, "g3-resumed-task-0001")
        assert resumed_task["retrieval_trace"]["injected_count"] == 1

        off_request = {
            **TASK_REQUEST,
            "memory_mode": "off",
            "current_constraints": {
                **TASK_REQUEST["current_constraints"],
                "memory_disabled": True,
            },
        }
        off_task = _terminal_task(client, "g3-memory-off-task-0001", off_request)
        assert off_task["retrieval_trace"]["candidate_count"] == 0
        assert off_task["public_plan"]["memory_summary"].startswith("本任务已关闭记忆模式")
    finally:
        client.__exit__(None, None, None)
