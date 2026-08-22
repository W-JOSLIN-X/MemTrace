from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "day1"
DAY2_FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "day2"
API_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "schemas" / "g0-api.schema.json"
EVENT_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "schemas" / "events.schema.json"

MOCK_FIXTURES = (
    FIXTURE_ROOT / "mock_sse_python_success.json",
    FIXTURE_ROOT / "mock_sse_no_tool_success.json",
    FIXTURE_ROOT / "mock_sse_failure.json",
)

FORBIDDEN_KEYS = {"reasoning_content", "api_key", "llm_api_key", "authorization"}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def schema_validator(
    root_schema: dict[str, Any], definition: str
) -> Draft202012Validator:
    selected = {
        "$schema": root_schema["$schema"],
        "$ref": f"#/$defs/{definition}",
        "$defs": root_schema["$defs"],
    }
    return Draft202012Validator(selected, format_checker=FormatChecker())


def assert_valid(validator: Draft202012Validator, instance: Any, label: str) -> None:
    errors = sorted(
        validator.iter_errors(instance), key=lambda error: list(error.absolute_path)
    )
    if not errors:
        return
    rendered = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        rendered.append(f"{location}: {error.message}")
    raise AssertionError(
        f"{label} failed schema validation:\n  " + "\n  ".join(rendered)
    )


def scan_forbidden(value: Any, path: str = "<root>") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise AssertionError(f"forbidden key {key!r} at {path}")
            scan_forbidden(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            scan_forbidden(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                raise AssertionError(f"credential-like text at {path}")


def materialize_demo_request(case: dict[str, Any]) -> dict[str, Any]:
    if "request" in case:
        return copy.deepcopy(case["request"])
    builder = case["input_builder"]
    request = copy.deepcopy(case["request_template"])
    request[builder["field"]] = builder["repeat"] * builder["count"]
    return request


def validate_demo_core(api_schema: dict[str, Any]) -> None:
    fixture = load_json(FIXTURE_ROOT / "demo_core.json")
    scan_forbidden(fixture, "demo_core")
    cases = fixture["cases"]
    assert len(cases) == 8, f"demo_core must contain 8 cases, got {len(cases)}"
    ids = [case["id"] for case in cases]
    assert len(set(ids)) == 8, "demo_core IDs must be unique"

    request_validator = schema_validator(api_schema, "TaskCreateRequest")
    for case in cases:
        request = materialize_demo_request(case)
        expected = case["expected"]
        trimmed_length = len(request["task_text"].strip())
        server_accepts_shape = 1 <= trimmed_length <= 20000
        assert server_accepts_shape == expected["accepted"], (
            f"{case['id']}: expected.accepted disagrees with trimmed task_text length"
        )
        if expected["accepted"]:
            assert_valid(request_validator, request, f"demo_core/{case['id']}/request")
            assert expected["http_status"] == 202
        else:
            assert expected["http_status"] == 422
            assert expected["error_code"] == "VALIDATION_ERROR"
            assert expected["creates_task"] is False
            if case["id"] != "whitespace_rejected":
                assert list(request_validator.iter_errors(request)), (
                    f"{case['id']}: rejected request unexpectedly passes the structural schema"
                )


def validate_feedback_drafts() -> None:
    fixture = load_json(FIXTURE_ROOT / "feedback_drafts.json")
    scan_forbidden(fixture, "feedback_drafts")
    assert fixture["day1_consumed"] is False
    drafts = fixture["drafts"]
    assert len(drafts) == 8, f"feedback_drafts must contain 8 drafts, got {len(drafts)}"
    assert len({draft["id"] for draft in drafts}) == 8
    for draft in drafts:
        rating = draft["rating"]
        assert rating is None or 1 <= rating <= 5, f"{draft['id']}: invalid rating"
        assert isinstance(draft["accepted"], bool)
        assert draft["explicit_text"] is not None or draft["edited_output"] is not None


def validate_day2_matrix() -> None:
    fixture = load_json(DAY2_FIXTURE_ROOT / "g1_classification_feedback_matrix.json")
    scan_forbidden(fixture, "g1_classification_feedback_matrix")
    assert fixture["contract_version"] == "1.1.0"
    assert fixture["classification_source"] == "auto_rule_v1"
    entries = fixture["entries"]
    assert len(entries) == 24, (
        f"Day 2 matrix must contain 24 entries, got {len(entries)}"
    )
    assert len({entry["id"] for entry in entries}) == 24
    profiles = fixture["persistent_event_profiles"]
    for entry in entries:
        assert entry["expected_domain"] in {
            "programming_learning",
            "software_development",
            "general_text",
            "other",
        }
        assert entry["expected_persistent_event_profile"] in profiles
        assert entry["expected_feedback_available_after"] == "succeeded_only"


def trace_signature(events: list[dict[str, Any]]) -> list[str]:
    signature: list[str] = []
    chunk_seen = False
    for event in events:
        event_type = event["event_type"]
        if event_type == "agent.chunk":
            if not chunk_seen:
                signature.append("agent.chunk+")
                chunk_seen = True
            continue
        if event_type == "task.stage":
            signature.append(f"task.stage:{event['data']['stage']}")
        else:
            signature.append(event_type)
    return signature


EXPECTED_TRACES = {
    "python_success": [
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
    "no_tool_success": [
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
    "run_failure": [
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
    ],
}


def validate_mock_fixture(
    path: Path,
    api_schema: dict[str, Any],
    event_validator: Draft202012Validator,
) -> None:
    fixture = load_json(path)
    scan_forbidden(fixture, path.name)
    assert fixture["simulated"] is True
    assert "MockProvider" in fixture["provider_evidence_label"]

    assert_valid(
        schema_validator(api_schema, "TaskCreateRequest"),
        fixture["request"],
        f"{path.name}/request",
    )
    assert_valid(
        schema_validator(api_schema, "TaskCreateAccepted"),
        fixture["accepted"],
        f"{path.name}/accepted",
    )
    assert_valid(
        schema_validator(api_schema, "TaskSnapshot"),
        fixture["terminal_snapshot"],
        f"{path.name}/terminal_snapshot",
    )

    events = fixture["events"]
    for index, event in enumerate(events):
        assert_valid(event_validator, event, f"{path.name}/events/{index}")
        assert event["task_id"] == fixture["accepted"]["task_id"]
        assert event["run_id"] == fixture["accepted"]["run_id"]

    persistent = [
        event["event_seq"] for event in events if event["event_seq"] is not None
    ]
    assert persistent == list(range(1, len(persistent) + 1)), (
        f"{path.name}: persistent event_seq is not contiguous"
    )
    assert len(persistent) == fixture["expectations"]["persistent_event_count"]

    chunks = [event["data"] for event in events if event["event_type"] == "agent.chunk"]
    assert len(chunks) == fixture["expectations"]["transient_chunk_count"]
    expected_offset = 0
    output_parts: list[str] = []
    for expected_seq, chunk in enumerate(chunks, start=1):
        assert chunk["chunk_seq"] == expected_seq
        assert chunk["run_id"] == fixture["accepted"]["run_id"]
        assert chunk["start_offset"] == expected_offset
        expected_offset += len(chunk["delta"].encode("utf-8"))
        assert chunk["end_offset"] == expected_offset
        output_parts.append(chunk["delta"])

    output = "".join(output_parts)
    snapshot = fixture["terminal_snapshot"]
    assert output == fixture["expectations"]["chunk_text"]
    assert output == snapshot["partial_output"]
    assert expected_offset == fixture["expectations"]["final_end_offset"]
    assert expected_offset == snapshot["end_offset"]
    assert snapshot["last_persistent_event_seq"] == persistent[-1]

    if snapshot["run_status"] == "succeeded":
        assert snapshot["final_message"]["content"] == output
        assert snapshot["error"] is None
    else:
        assert snapshot["final_message"] is None
        assert (
            snapshot["error"]["code"] == fixture["expectations"]["terminal_error_code"]
        )

    trace_name = fixture["expectations"]["trace"]
    assert trace_signature(events) == EXPECTED_TRACES[trace_name], (
        f"{path.name}: trace does not match {trace_name}"
    )

    tool_events = [event for event in events if event["event_type"] == "tool.called"]
    if fixture["name"] == "python_success":
        match = re.search(
            r"```(?:python|py)\s*\n(.*?)```",
            fixture["request"]["task_text"],
            re.DOTALL | re.IGNORECASE,
        )
        assert match is not None
        assert (
            len(match.group(1).encode("utf-8"))
            == tool_events[0]["data"]["args_summary"]["code_bytes"]
        )
    else:
        assert not tool_events


def main() -> int:
    api_schema = load_json(API_SCHEMA_PATH)
    event_schema = load_json(EVENT_SCHEMA_PATH)
    Draft202012Validator.check_schema(api_schema)
    Draft202012Validator.check_schema(event_schema)
    event_validator = Draft202012Validator(event_schema, format_checker=FormatChecker())

    validate_demo_core(api_schema)
    validate_feedback_drafts()
    validate_day2_matrix()
    for path in MOCK_FIXTURES:
        validate_mock_fixture(path, api_schema, event_validator)

    print("PASS: both Draft 2020-12 schemas are structurally valid")
    print("PASS: 8 demo_core cases, 8 feedback drafts, and 24 Day 2 G1 matrix entries")
    print("PASS: python_success, no_tool_success, and run_failure SSE fixtures")
    print(
        "PASS: UTF-8 byte offsets, trace order, metadata IDs, and secret/reasoning scan"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error
