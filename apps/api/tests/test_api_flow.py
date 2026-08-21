from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from memtrace_api.config import Settings
from memtrace_api.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "day1"
EVENT_SCHEMA = json.loads(
    (PROJECT_ROOT / "contracts" / "schemas" / "events.schema.json").read_text(encoding="utf-8")
)
API_SCHEMA = json.loads(
    (PROJECT_ROOT / "contracts" / "schemas" / "g0-api.schema.json").read_text(encoding="utf-8")
)
EVENT_VALIDATOR = Draft202012Validator(EVENT_SCHEMA, format_checker=FormatChecker())


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _validate_api_model(name: str, value: dict[str, Any]) -> None:
    selected = {
        "$schema": API_SCHEMA["$schema"],
        "$ref": f"#/$defs/{name}",
        "$defs": API_SCHEMA["$defs"],
    }
    Draft202012Validator(selected, format_checker=FormatChecker()).validate(value)


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    values: dict[str, object] = {
        "app_env": "test",
        "mock_mode": True,
        "memtrace_data_dir": tmp_path / "data",
        "mock_chunk_delay_ms": 250,
    }
    values.update(overrides)
    return TestClient(create_app(Settings(_env_file=None, **values)))


def _read_sse(client: TestClient, url: str, **kwargs: Any) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    with client.stream("GET", url, **kwargs) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"
        raw = "".join(response.iter_text()).replace("\r\n", "\n")

    for block in raw.split("\n\n"):
        lines = [line for line in block.splitlines() if line]
        if not lines or lines[0].startswith(":"):
            continue
        sse_id = next((line[4:] for line in lines if line.startswith("id: ")), None)
        event_name = next(line[7:] for line in lines if line.startswith("event: "))
        data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        assert event_name == data["event_type"]
        if data["event_seq"] is None:
            assert sse_id is None
        else:
            assert sse_id == str(data["event_seq"])
        EVENT_VALIDATOR.validate(data)
        parsed.append(data)
    return parsed


def _trace_signature(events: list[dict[str, Any]]) -> list[str]:
    signature: list[str] = []
    chunk_seen = False
    for event in events:
        if event["event_type"] == "agent.chunk":
            if not chunk_seen:
                signature.append("agent.chunk+")
                chunk_seen = True
        elif event["event_type"] == "task.stage":
            signature.append(f"task.stage:{event['data']['stage']}")
        else:
            signature.append(event["event_type"])
    return signature


@pytest.mark.parametrize(
    ("fixture_name", "expected_trace"),
    [
        (
            "mock_sse_python_success.json",
            [
                "task.created",
                "task.stage:fingerprinting",
                "task.fingerprinted",
                "task.stage:retrieving",
                "memory.retrieval.started",
                "task.stage:planning",
                "agent.plan.published",
                "task.stage:tool_running",
                "tool.called",
                "tool.result",
                "task.stage:generating",
                "agent.chunk+",
                "run.metrics",
                "run.completed",
                "stream.done",
            ],
        ),
        (
            "mock_sse_no_tool_success.json",
            [
                "task.created",
                "task.stage:fingerprinting",
                "task.fingerprinted",
                "task.stage:retrieving",
                "memory.retrieval.started",
                "task.stage:planning",
                "agent.plan.published",
                "task.stage:generating",
                "agent.chunk+",
                "run.metrics",
                "run.completed",
                "stream.done",
            ],
        ),
    ],
)
def test_mock_success_flow_matches_contract_and_fixture_output(
    tmp_path: Path,
    fixture_name: str,
    expected_trace: list[str],
) -> None:
    fixture = _load_fixture(fixture_name)
    with _client(tmp_path) as client:
        accepted_response = client.post("/api/v1/tasks", json=fixture["request"])
        assert accepted_response.status_code == 202
        accepted = accepted_response.json()
        assert accepted["provider_mode"] == "mock"
        assert accepted["effective_memory_mode"] == fixture["accepted"]["effective_memory_mode"]
        _validate_api_model("TaskCreateAccepted", accepted)

        # The runner has published its fast metadata before the first browser
        # subscription. The initial replay must still contain the full trace.
        time.sleep(0.005)
        events = _read_sse(client, accepted["events_url"])
        snapshot_response = client.get(f"/api/v1/tasks/{accepted['task_id']}")

    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    _validate_api_model("TaskSnapshot", snapshot)
    assert _trace_signature(events) == expected_trace
    assert events[-1]["event_type"] == "stream.done"
    assert events[-1]["data"]["status"] == "succeeded"
    chunks = [event["data"] for event in events if event["event_type"] == "agent.chunk"]
    output = "".join(chunk["delta"] for chunk in chunks)
    assert output == fixture["expectations"]["chunk_text"]
    assert snapshot["partial_output"] == output
    assert snapshot["final_message"]["content"] == output
    assert snapshot["end_offset"] == len(output.encode("utf-8"))
    assert snapshot["run_status"] == "succeeded"
    assert snapshot["terminal"] is True
    persistent = [event["event_seq"] for event in events if event["event_seq"] is not None]
    assert persistent == list(range(1, len(persistent) + 1))
    assert len(persistent) == fixture["expectations"]["persistent_event_count"]
    rendered = json.dumps(events, ensure_ascii=False)
    assert "reasoning_content" not in rendered
    assert fixture["request"]["task_text"] not in rendered


def test_mock_failure_keeps_partial_output_and_has_no_silent_retry(tmp_path: Path) -> None:
    fixture = _load_fixture("mock_sse_failure.json")
    with _client(tmp_path) as client:
        accepted = client.post("/api/v1/tasks", json=fixture["request"]).json()
        events = _read_sse(client, accepted["events_url"])
        snapshot = client.get(f"/api/v1/tasks/{accepted['task_id']}").json()

    _validate_api_model("TaskSnapshot", snapshot)
    expected_trace = [
        "task.created",
        "task.stage:fingerprinting",
        "task.fingerprinted",
        "task.stage:retrieving",
        "memory.retrieval.started",
        "task.stage:planning",
        "agent.plan.published",
        "task.stage:generating",
        "agent.chunk+",
        "run.metrics",
        "task.stage:failed",
        "run.failed",
        "error",
        "stream.done",
    ]
    assert _trace_signature(events) == expected_trace
    chunks = [event["data"] for event in events if event["event_type"] == "agent.chunk"]
    assert "".join(chunk["delta"] for chunk in chunks) == fixture["expectations"]["chunk_text"]
    assert [chunk["chunk_seq"] for chunk in chunks] == [1, 2]
    assert snapshot["run_status"] == "failed"
    assert snapshot["partial_output"] == fixture["expectations"]["chunk_text"]
    assert snapshot["final_message"] is None
    assert snapshot["error"]["code"] == "PROVIDER_ERROR"
    assert snapshot["effective_memory_mode"] == "off"


@pytest.mark.parametrize(
    "task_text",
    ["   \n\t ", "x" * 20_001],
    ids=["whitespace", "overlong"],
)
def test_empty_and_overlong_task_are_rejected_without_creating_a_task(
    tmp_path: Path,
    task_text: str,
) -> None:
    request = _load_fixture("mock_sse_no_tool_success.json")["request"]
    request["task_text"] = task_text
    with _client(tmp_path) as client:
        response = client.post("/api/v1/tasks", json=request)
        store = client.app.state.store
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert not store._tasks


def test_lone_surrogate_is_rejected_before_background_processing(tmp_path: Path) -> None:
    request = _load_fixture("mock_sse_no_tool_success.json")["request"]
    request["task_text"] = "invalid-\ud800-unicode"
    body = json.dumps(request, ensure_ascii=True).encode("ascii")
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/tasks",
            content=body,
            headers={"content-type": "application/json"},
        )
        store = client.app.state.store
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert not store._tasks


def test_validation_field_errors_are_bounded_and_schema_valid(tmp_path: Path) -> None:
    request = _load_fixture("mock_sse_no_tool_success.json")["request"]
    request.update({f"unknown_{index}": index for index in range(60)})
    with _client(tmp_path) as client:
        response = client.post("/api/v1/tasks", json=request)
        store = client.app.state.store
    assert response.status_code == 422
    body = response.json()
    _validate_api_model("ErrorResponse", body)
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert len(body["error"]["details"]["field_errors"]) == 50
    assert not store._tasks


def test_unknown_task_and_unknown_route_have_distinct_safe_errors(tmp_path: Path) -> None:
    missing_id = "task_01J00000000000000000000001"
    with _client(tmp_path) as client:
        task_response = client.get(f"/api/v1/tasks/{missing_id}")
        route_response = client.get("/api/v1/nope")
    assert task_response.status_code == 404
    assert task_response.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert task_response.json()["error"]["details"]["task_id"] == missing_id
    assert route_response.status_code == 404
    assert route_response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert route_response.json()["error"]["details"]["http_status"] == 404


def test_static_dist_serves_assets_and_spa_without_shadowing_api(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main>MemTrace</main>", encoding="utf-8")
    (assets / "app.js").write_text("window.memtrace=true", encoding="utf-8")

    with _client(tmp_path, memtrace_web_dist=dist) as client:
        root = client.get("/")
        asset = client.get("/assets/app.js")
        frontend_route = client.get("/memories")
        unknown_api = client.get("/api/v1/nope")

    assert root.status_code == 200
    assert root.text == "<main>MemTrace</main>"
    assert asset.status_code == 200
    assert asset.text == "window.memtrace=true"
    assert frontend_route.status_code == 200
    assert frontend_route.text == root.text
    assert unknown_api.status_code == 404
    assert unknown_api.headers["content-type"].startswith("application/json")
    assert unknown_api.json()["error"]["code"] == "VALIDATION_ERROR"


def test_missing_static_dist_does_not_affect_api(tmp_path: Path) -> None:
    with _client(tmp_path, memtrace_web_dist=tmp_path / "missing") as client:
        health = client.get("/api/v1/health")
        root = client.get("/")
    assert health.status_code == 200
    assert root.status_code == 404
    assert root.json()["error"]["code"] == "VALIDATION_ERROR"
