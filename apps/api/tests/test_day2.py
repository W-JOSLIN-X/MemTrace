"""Day 2 G1 integration tests: owner isolation, feedback, idempotency, restart."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from memtrace_api.config import PROJECT_ROOT, Settings
from memtrace_api.database import session_scope
from memtrace_api.db_models import (
    EventLogModel,
    FeedbackEventModel,
    IdempotencyKeyModel,
    MemoryJobModel,
    TaskFingerprintModel,
    TaskModel,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.logic import analyze_task
from memtrace_api.main import create_app
from memtrace_api.repositories import (
    IdempotencyRepository,
    TaskRepository,
    UserContext,
    UserRepository,
)
from memtrace_api.schemas import ProviderMode, TaskCreateRequest

TEST_SESSION_SECRET = "test_session_secret_01234567890123456789"

NO_TOOL_REQUEST: dict[str, Any] = {
    "task_text": "请用一句话解释什么是递归，并给我一个直观比喻。🙂",
    "memory_mode": "on",
    "current_constraints": {
        "response_policy": "guided_hint",
        "urgency": "normal",
        "memory_disabled": False,
        "source": "ui",
    },
}


def _migrate(db_url: str) -> None:
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


@contextlib.contextmanager
def _client(
    tmp_path: Path,
    *,
    alias: str = "blank_demo",
    db_url: str | None = None,
) -> Iterator[TestClient]:
    """A logged-in TestClient whose lifespan (and orchestrator loop) stays alive."""
    resolved_db_url = db_url or f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}"
    _migrate(resolved_db_url)
    settings = Settings(
        _env_file=None,
        app_env="test",
        mock_mode=True,
        memtrace_data_dir=tmp_path / "data",
        memtrace_database_url=resolved_db_url,
        session_secret=TEST_SESSION_SECRET,
    )
    client = TestClient(
        create_app(settings),
        headers={"Idempotency-Key": "test-idempotency-key-0001"},
    )
    with client:
        login = client.post("/api/v1/session/demo", json={"demo_alias": alias})
        assert login.status_code == 200, login.text
        yield client


def _run_task_to_terminal(client: TestClient, *, task_text: str | None = None) -> dict[str, Any]:
    """Create a task, drain its SSE stream to completion, and return the accepted payload."""
    body = dict(NO_TOOL_REQUEST)
    if task_text is not None:
        body["task_text"] = task_text
    accepted = client.post("/api/v1/tasks", json=body)
    assert accepted.status_code == 202, accepted.text
    payload = accepted.json()

    # Let the orchestrator publish its fast metadata before the first SSE
    # subscription opens (mirrors the Day 1 flow test timing).
    time.sleep(0.005)
    events: list[dict[str, Any]] = []
    with client.stream("GET", payload["events_url"]) as response:
        assert response.status_code == 200, response.text
        raw = "".join(response.iter_text()).replace("\r\n", "\n")
    for block in raw.split("\n\n"):
        lines = [line for line in block.splitlines() if line]
        if not lines or lines[0].startswith(":"):
            continue
        events.append(json.loads(next(line[6:] for line in lines if line.startswith("data: "))))

    assert events[-1]["event_type"] == "stream.done"
    return payload


def _row_count(client: TestClient, model: Any) -> int:
    with session_scope(client.app.state.db_session_factory) as session:
        return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_missing_cookie_returns_session_required(tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}"
    _migrate(db_url)
    settings = Settings(
        _env_file=None,
        app_env="test",
        mock_mode=True,
        memtrace_data_dir=tmp_path / "data",
        memtrace_database_url=db_url,
        session_secret=TEST_SESSION_SECRET,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/tasks",
            json=NO_TOOL_REQUEST,
            headers={"Idempotency-Key": "test-idempotency-key-0001"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_REQUIRED"


def test_demo_alias_whitelist_and_cookie_is_opaque(tmp_path: Path) -> None:
    with _client(tmp_path, alias="seeded_demo") as client:
        session = client.get("/api/v1/session")
        assert session.status_code == 200
        assert session.json()["demo_alias"] == "seeded_demo"

        cookie = client.cookies.get("memtrace_demo_session")
        assert cookie is not None
        # Cookie must not contain alias or owner_id as plaintext.
        assert "seeded_demo" not in cookie
        assert "usr_" not in cookie

    with _client(tmp_path) as client:
        response = client.post("/api/v1/session/demo", json={"demo_alias": "not_a_real_alias"})
        assert response.status_code == 422


def test_session_switch_revokes_exact_prior_cookie_and_reports_current_expiry(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, alias="blank_demo") as client:
        old_cookie = client.cookies.get("memtrace_demo_session")
        assert old_cookie is not None

        switched = client.post(
            "/api/v1/session/demo",
            json={"demo_alias": "seeded_demo"},
        )
        assert switched.status_code == 200
        new_cookie = client.cookies.get("memtrace_demo_session")
        assert new_cookie is not None and new_cookie != old_cookie

        current = client.get("/api/v1/session")
        assert current.status_code == 200
        assert current.json()["demo_alias"] == "seeded_demo"
        assert current.json()["expires_at"] == switched.json()["expires_at"]

        client.cookies.clear()
        client.cookies.set("memtrace_demo_session", old_cookie)
        assert client.get("/api/v1/session").status_code == 401

        client.cookies.clear()
        client.cookies.set("memtrace_demo_session", new_cookie)
        assert client.get("/api/v1/session").status_code == 200


def test_owner_isolation_across_task_feedback_and_sse(tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}"
    with _client(tmp_path, alias="blank_demo", db_url=db_url) as client_a:
        payload = _run_task_to_terminal(client_a)
        task_id = payload["task_id"]
        assert client_a.get(f"/api/v1/tasks/{task_id}").status_code == 200

        with _client(tmp_path, alias="seeded_demo", db_url=db_url) as client_b:
            assert client_b.get(f"/api/v1/tasks/{task_id}").status_code == 404
            with client_b.stream("GET", f"/api/v1/tasks/{task_id}/events") as resp:
                assert resp.status_code == 404
            fb = client_b.post(
                f"/api/v1/tasks/{task_id}/feedback",
                json={"explicit_text": "好的建议"},
                headers={"Idempotency-Key": "test-idempotency-key-0002"},
            )
            assert fb.status_code == 404


def test_terminal_task_restarts_and_recovers_messages(tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}"
    with _client(tmp_path, db_url=db_url) as client_a:
        payload = _run_task_to_terminal(client_a)
        task_id = payload["task_id"]

    # "Restart": build a fresh app + fresh TaskStore against the same DB.
    with _client(tmp_path, db_url=db_url) as client_b:
        snapshot = client_b.get(f"/api/v1/tasks/{task_id}")
        assert snapshot.status_code == 200
        body = snapshot.json()
        assert body["run_status"] == "succeeded"
        assert body["terminal"] is True
        assert body["task_text"] == NO_TOOL_REQUEST["task_text"]
        roles = [m["role"] for m in body["messages"]]
        assert "user" in roles and "assistant" in roles
        assistant = next(m for m in body["messages"] if m["role"] == "assistant")
        assert assistant["content"] == body["partial_output"]


def test_restart_marks_preexisting_nonterminal_run_interrupted(tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}"
    request = TaskCreateRequest.model_validate(NO_TOOL_REQUEST)
    analysis = analyze_task(request)
    task_id = new_prefixed_ulid("task")
    run_id = new_prefixed_ulid("run")

    with _client(tmp_path, db_url=db_url) as client_a:
        with session_scope(client_a.app.state.db_session_factory) as session:
            user = UserRepository(session).get_by_alias("blank_demo")
            assert user is not None
            user_ctx = UserContext(user_id=user.id, demo_alias=user.demo_alias)
            TaskRepository(user_ctx, session).create_task(
                task_id=task_id,
                run_id=run_id,
                request=request,
                detected_domain=analysis.fingerprint.domain,
                provider_mode=ProviderMode.MOCK,
                model="mock-g0",
            )

    with _client(tmp_path, db_url=db_url) as client_b:
        response = client_b.get(f"/api/v1/tasks/{task_id}")

    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["run_status"] == "failed"
    assert snapshot["terminal"] is True
    assert snapshot["error"]["code"] == "RUN_INTERRUPTED"


def test_server_classification_is_identical_in_db_fingerprint_and_snapshot(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(
            client,
            task_text="请审查并重构这段 React 组件代码",
        )
        snapshot = client.get(f"/api/v1/tasks/{payload['task_id']}").json()
        with session_scope(client.app.state.db_session_factory) as session:
            task = session.execute(
                select(TaskModel).where(TaskModel.id == payload["task_id"])
            ).scalar_one()
            fingerprint_row = session.execute(
                select(TaskFingerprintModel).where(
                    TaskFingerprintModel.task_id == payload["task_id"]
                )
            ).scalar_one()

    fingerprint_json = json.loads(fingerprint_row.fingerprint_json)
    assert snapshot["scenario"] == "software_development"
    assert snapshot["scenario"] == snapshot["fingerprint"]["domain"]
    assert task.scenario == snapshot["scenario"]
    assert fingerprint_json["domain"] == snapshot["scenario"]
    assert fingerprint_json["classification_source"] == "auto_rule_v1"


def test_agent_chunk_not_in_event_log(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client)
        with session_scope(client.app.state.db_session_factory) as session:
            event_types = set(
                session.execute(
                    select(EventLogModel.event_type).where(
                        EventLogModel.stream_id == payload["task_id"]
                    )
                )
                .scalars()
                .all()
            )
    assert "agent.chunk" not in event_types


def test_event_log_excludes_task_answer_and_feedback_body(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client)
        task_id = payload["task_id"]
        fb = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "以后先提示我观察边界", "rating": 4},
            headers={"Idempotency-Key": "test-idempotency-key-0003"},
        )
        assert fb.status_code == 202, fb.text

        with session_scope(client.app.state.db_session_factory) as session:
            blobs = (
                session.execute(
                    select(EventLogModel.metadata_json).where(EventLogModel.stream_id == task_id)
                )
                .scalars()
                .all()
            )
    joined = json.dumps(blobs, ensure_ascii=False)
    assert NO_TOOL_REQUEST["task_text"] not in joined
    assert "以后先提示我观察边界" not in joined


def test_feedback_same_transaction_creates_feedback_job_and_event(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client)
        task_id = payload["task_id"]

        fb = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "以后先提示我观察边界", "rating": 4, "accepted": True},
            headers={"Idempotency-Key": "test-idempotency-key-0004"},
        )
        assert fb.status_code == 202, fb.text
        fb_body = fb.json()
        assert fb_body["feedback_type"] == "composite"
        assert fb_body["job_status"] == "pending"

        job = client.get(f"/api/v1/memory-jobs/{fb_body['memory_job_id']}")
        assert job.status_code == 200
        assert job.json()["status"] == "pending"

        snap = client.get(f"/api/v1/tasks/{task_id}").json()
        assert len(snap["feedback_events"]) == 1
        assert snap["feedback_events"][0]["feedback_id"] == fb_body["feedback_id"]
        assert snap["feedback_events"][0]["memory_job_id"] == fb_body["memory_job_id"]


def test_feedback_mid_transaction_failure_rolls_back_every_durable_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client)
        task_id = payload["task_id"]
        before = {
            "feedback": _row_count(client, FeedbackEventModel),
            "jobs": _row_count(client, MemoryJobModel),
            "events": _row_count(client, EventLogModel),
            "idempotency": _row_count(client, IdempotencyKeyModel),
        }

        def fail_idempotency_save(*args: object, **kwargs: object) -> None:
            raise RuntimeError("forced transactional rollback")

        monkeypatch.setattr(IdempotencyRepository, "save_record", fail_idempotency_save)
        response = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "这条反馈必须整体回滚"},
            headers={"Idempotency-Key": "feedback-rollback-key-0001"},
        )

        after = {
            "feedback": _row_count(client, FeedbackEventModel),
            "jobs": _row_count(client, MemoryJobModel),
            "events": _row_count(client, EventLogModel),
            "idempotency": _row_count(client, IdempotencyKeyModel),
        }

    assert response.status_code == 500
    assert after == before


def test_edited_output_does_not_overwrite_original_message(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client)
        task_id = payload["task_id"]

        original_output = client.get(f"/api/v1/tasks/{task_id}").json()["partial_output"]

        fb = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"edited_output": "用户修改后的全新内容"},
            headers={"Idempotency-Key": "test-idempotency-key-0005"},
        )
        assert fb.status_code == 202, fb.text

        restored = client.get(f"/api/v1/tasks/{task_id}").json()
        assistant = next(m for m in restored["messages"] if m["role"] == "assistant")
        assert assistant["content"] == original_output
        assert restored["feedback_events"][0]["edited_output"] == "用户修改后的全新内容"


def test_idempotent_replay_returns_same_ids_and_does_not_create_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client)
        task_id = payload["task_id"]

        before_jobs = _row_count(client, MemoryJobModel)
        before_feedback = _row_count(client, FeedbackEventModel)

        key = "test-idempotency-key-0006"
        fb_1 = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "以后先提示我观察边界"},
            headers={"Idempotency-Key": key},
        )
        fb_2 = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "以后先提示我观察边界"},
            headers={"Idempotency-Key": key},
        )
        assert fb_1.status_code == 202
        assert fb_2.status_code == 202
        assert fb_1.json()["feedback_id"] == fb_2.json()["feedback_id"]
        assert fb_1.json()["memory_job_id"] == fb_2.json()["memory_job_id"]

        assert _row_count(client, FeedbackEventModel) == before_feedback + 1
        assert _row_count(client, MemoryJobModel) == before_jobs + 1


def test_idempotent_conflict_same_key_different_body(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client)
        task_id = payload["task_id"]

        key = "test-idempotency-key-0007"
        client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "以后先提示我观察边界"},
            headers={"Idempotency-Key": key},
        )
        conflict = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "不同的反馈内容"},
            headers={"Idempotency-Key": key},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_feedback_validation_rejections(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client)
        task_id = payload["task_id"]

        for bad_rating in (0, 6, -1, True, 3.5, "4"):
            resp = client.post(
                f"/api/v1/tasks/{task_id}/feedback",
                json={"rating": bad_rating},
                headers={"Idempotency-Key": "test-idempotency-key-0008"},
            )
            assert resp.status_code == 422, (bad_rating, resp.text)

        resp = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={},
            headers={"Idempotency-Key": "test-idempotency-key-0008"},
        )
        assert resp.status_code == 422

        resp = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "   "},
            headers={"Idempotency-Key": "test-idempotency-key-0008"},
        )
        assert resp.status_code == 422

        original = client.get(f"/api/v1/tasks/{task_id}").json()["partial_output"]
        resp = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"edited_output": original},
            headers={"Idempotency-Key": "test-idempotency-key-0008"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "FEEDBACK_NO_CHANGES"


def test_other_owner_job_returns_404(tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}"
    with _client(tmp_path, alias="blank_demo", db_url=db_url) as client_a:
        payload = _run_task_to_terminal(client_a)
        task_id = payload["task_id"]
        fb = client_a.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "以后先提示我观察边界"},
            headers={"Idempotency-Key": "test-idempotency-key-0009"},
        )
        job_id = fb.json()["memory_job_id"]
        assert client_a.get(f"/api/v1/memory-jobs/{job_id}").status_code == 200

        with _client(tmp_path, alias="seeded_demo", db_url=db_url) as client_b:
            assert client_b.get(f"/api/v1/memory-jobs/{job_id}").status_code == 404


def test_generating_or_failed_task_cannot_accept_feedback(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client, task_text="测试时在首个 chunk 后强制 Provider 失败")
        task_id = payload["task_id"]
        snap = client.get(f"/api/v1/tasks/{task_id}").json()
        assert snap["run_status"] == "failed"

        fb = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "好的建议"},
            headers={"Idempotency-Key": "test-idempotency-key-0010"},
        )
        assert fb.status_code == 409
        assert fb.json()["error"]["code"] == "TASK_NOT_READY_FOR_FEEDBACK"


def test_post_run_metadata_catchup_replays_feedback_recorded_once(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _run_task_to_terminal(client)
        task_id = payload["task_id"]

        stream_done_seq = client.get(f"/api/v1/tasks/{task_id}").json()["last_persistent_event_seq"]

        fb = client.post(
            f"/api/v1/tasks/{task_id}/feedback",
            json={"explicit_text": "以后先提示我观察边界"},
            headers={"Idempotency-Key": "test-idempotency-key-0011"},
        )
        assert fb.status_code == 202, fb.text

        with client.stream(
            "GET", f"/api/v1/tasks/{task_id}/events?after_event_seq={stream_done_seq}"
        ) as resp:
            assert resp.status_code == 200
            raw = "".join(resp.iter_text()).replace("\r\n", "\n")

        events = []
        for block in raw.split("\n\n"):
            lines = [line for line in block.splitlines() if line]
            if not lines or lines[0].startswith(":"):
                continue
            events.append(json.loads(next(line[6:] for line in lines if line.startswith("data: "))))

        assert [e["event_type"] for e in events] == ["feedback.recorded"]
        assert events[0]["data"]["feedback_id"] == fb.json()["feedback_id"]

        snap = client.get(f"/api/v1/tasks/{task_id}").json()
        assert snap["feedback_events"][0]["feedback_id"] == fb.json()["feedback_id"]
