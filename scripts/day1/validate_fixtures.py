from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "day1"
DAY2_FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "day2"
DAY3_FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "day3"
DAY4_FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "day4"
DAY5_FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "day5"
DAY6_FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "day6"
API_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "schemas" / "g0-api.schema.json"
EVENT_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "schemas" / "events.schema.json"
G5_LLM_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "schemas" / "g5-llm.schema.json"
G5_EXAMPLES_PATH = PROJECT_ROOT / "contracts" / "examples" / "day6-g5.json"

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


def validate_day3_learning_events(api_schema: dict[str, Any]) -> None:
    fixture = load_json(DAY3_FIXTURE_ROOT / "learning_events.json")
    scan_forbidden(fixture, "learning_events")
    assert fixture["contract_version"] == "1.2.0"
    assert fixture["review_status"] == "member_b_approved_2026-08-24"
    entries = fixture["entries"]
    assert len(entries) >= 24, (
        f"Day 3 learning events need >=24 entries, got {len(entries)}"
    )
    assert len({entry["id"] for entry in entries}) == len(entries)

    durability_values = {
        "explicit_durable",
        "one_shot",
        "ambiguous",
        "reinforce_usage_only",
        "harmful_usage_only",
    }
    categories = {"preference", "rule", "experience", "one_shot", "no_memory"}
    dispositions = {
        "candidate_created",
        "episode_only",
        "reinforce_usage_only",
        "no_memory",
        "failed",
    }
    kinds = {
        "preference",
        "constraint",
        "procedure",
        "experience",
        "environment",
        "learning_checkpoint",
    }
    domains = {"programming_learning", "software_development", "general_text", "other"}
    task_types = {
        "debugging_guidance",
        "code_review",
        "code_explanation",
        "code_generation",
        "environment_configuration",
        "general_question",
        "other",
    }
    stage_paths = fixture["stage_paths"]
    declared_sims = set(fixture["provider_simulations"])
    feedback_validator = schema_validator(api_schema, "FeedbackCreateRequest")

    seen_durability: set[str] = set()
    seen_candidate_counts: set[int] = set()
    for entry in entries:
        label = f"learning_events/{entry['id']}"
        assert entry["task_text"].strip(), f"{label}: empty task_text"
        fingerprint = entry["expected_fingerprint"]
        assert fingerprint["domain"] in domains, f"{label}: bad domain"
        assert fingerprint["task_type"] in task_types, f"{label}: bad task_type"

        feedback = entry["feedback"]
        non_null = {key: value for key, value in feedback.items() if value is not None}
        assert non_null, f"{label}: feedback must carry at least one signal"
        assert_valid(feedback_validator, feedback, f"{label}/feedback")

        simulation = entry["provider_simulation"]
        assert simulation is None or simulation in declared_sims, (
            f"{label}: unknown simulation"
        )

        expected = entry["expected"]
        assert expected["durability"] in durability_values, f"{label}: bad durability"
        assert expected["durability_reason"] in fixture["durability_reason_codes"], (
            f"{label}: bad durability_reason"
        )
        assert expected["category"] in categories, f"{label}: bad category"
        assert expected["disposition"] in dispositions, f"{label}: bad disposition"
        assert expected["stage_events"] in stage_paths, f"{label}: unknown stage path"

        count = expected["candidate_count"]
        kinds_expected = expected["candidate_kinds"]
        assert 0 <= count <= 3, f"{label}: candidate_count out of 0..3"
        assert len(kinds_expected) == count, f"{label}: kinds length mismatch"
        assert all(kind in kinds for kind in kinds_expected), f"{label}: bad kind"
        assert expected["candidate_created_events"] == count, (
            f"{label}: candidate events must equal candidate_count"
        )
        if expected["save_preselected"]:
            assert count >= 1, f"{label}: save_preselected requires candidates"
        if expected["durability"] != "explicit_durable":
            assert not expected["save_preselected"], (
                f"{label}: only explicit_durable may preselect save"
            )
        if expected["category"] == "preference":
            assert set(kinds_expected) <= {"preference"}, (
                f"{label}: preference kind drift"
            )
        elif expected["category"] == "rule":
            assert set(kinds_expected) <= {"constraint", "procedure"}, (
                f"{label}: rule maps to constraint|procedure"
            )
        elif expected["category"] == "experience":
            assert set(kinds_expected) <= {"experience"}, (
                f"{label}: experience kind drift"
            )
        else:
            assert count == 0, f"{label}: one_shot/no_memory cannot create cards"

        if expected["job_status"] == "failed":
            assert expected["job_error_code"] is not None, (
                f"{label}: failed needs error code"
            )
            assert expected["job_failed_event"] is True, (
                f"{label}: failed needs failure event"
            )
            assert expected["disposition"] == "failed", f"{label}: failed disposition"
        else:
            assert expected["job_error_code"] is None, (
                f"{label}: completed has no error"
            )
            assert expected["job_failed_event"] is False, (
                f"{label}: unexpected failure event"
            )

        if feedback["edited_output"] is not None:
            original = entry["original_assistant_output"]
            assert original is not None, f"{label}: diff entries need original output"
            assert original != feedback["edited_output"], (
                f"{label}: diff must change content"
            )
        else:
            assert entry["original_assistant_output"] is None, (
                f"{label}: original output only for diff entries"
            )

        seen_durability.add(expected["durability"])
        seen_candidate_counts.add(count)

    assert seen_durability == durability_values, (
        f"learning_events must cover every durability, missing: {durability_values - seen_durability}"
    )
    assert {0, 1, 2, 3} <= seen_candidate_counts, (
        f"learning_events must cover 0/1/2/3 candidate counts, missing: "
        f"{ {0, 1, 2, 3} - seen_candidate_counts }"
    )
    assert any(
        entry["provider_simulation"] == "evidence_not_found" for entry in entries
    ), "learning_events must cover evidence_quote-not-a-substring"
    assert any(entry["expected"]["job_status"] == "failed" for entry in entries), (
        "learning_events must cover a repair-still-fails job"
    )
    english = [
        e
        for e in entries
        if e["feedback"]["explicit_text"] and e["feedback"]["explicit_text"].isascii()
    ]
    assert english, "learning_events must include English feedback"
    chinese = [
        e
        for e in entries
        if e["feedback"]["explicit_text"]
        and not e["feedback"]["explicit_text"].isascii()
    ]
    assert chinese, "learning_events must include Chinese feedback"


def validate_day4_g3_cases() -> None:
    fixture = load_json(DAY4_FIXTURE_ROOT / "g3_retrieval_cases.json")
    scan_forbidden(fixture, "g3_retrieval_cases")
    assert fixture["contract_version"] == "1.3.0"
    assert fixture["review_status"] == "member_b_verified_2026-08-25"
    assert fixture["approval_claim"] == "owner_verified_not_joint_approval"
    assert fixture["transport"] == "rest_only"
    assert fixture["privacy"] == "metadata_only_results"
    cases = fixture["cases"]
    assert len(cases) == 30, f"Day 4 G3 fixture must contain 30 cases, got {len(cases)}"
    assert len({case["id"] for case in cases}) == 30
    assert {case["id"] for case in cases} == {
        f"d4-g3-{index:02d}" for index in range(1, 31)
    }
    required_operations = {
        "retrieve",
        "negative",
        "status_filter",
        "pause",
        "resume",
        "memory_off",
        "override",
        "budget_single",
        "budget_total",
        "hash",
        "recovery",
        "verifier",
        "owner_isolation",
    }
    operations = {case["operation"] for case in cases}
    assert required_operations <= operations
    for case in cases:
        assert re.fullmatch(r"d4-r\d{2}", case["source"])
        assert isinstance(case["expected"], dict) and case["expected"]
        if "task_text" in case:
            assert 1 <= len(case["task_text"].strip()) <= 20_000
            assert case["memory_mode"] in {"on", "off"}
            assert case["response_policy"] in {"default", "guided_hint", "direct_fix"}


def validate_day5_g4_cases() -> None:
    conflict = load_json(DAY5_FIXTURE_ROOT / "g4_conflict_cases.json")
    security = load_json(DAY5_FIXTURE_ROOT / "g4_pack_security_cases.json")
    for fixture, count, prefix in (
        (conflict, 8, "d5-g4-conflict-"),
        (security, 12, "d5-g4-pack-"),
    ):
        scan_forbidden(fixture, prefix)
        assert fixture["contract_version"] == "1.4.0"
        assert fixture["review_status"] == "member_b_verified_2026-08-26"
        assert fixture["transport"] == "rest_only"
        assert fixture["split"] == "g4_split_v1"
        cases = fixture["cases"]
        assert len(cases) == count, f"{prefix} expected {count} cases"
        assert {case["id"] for case in cases} == {
            f"{prefix}{index:02d}" for index in range(1, count + 1)
        }
        assert all(case["operation"] and case["expected"] for case in cases)
    assert {case["action"] for case in conflict["cases"]} >= {
        "prefer",
        "separate_scopes",
        "merge",
        "pause_both",
    }
    required_security = {
        "round_trip",
        "oversized_file",
        "duplicate_keys",
        "unsupported_version",
        "integrity_mismatch",
        "dangling_relation",
        "self_relation",
        "forbidden_field",
        "xss_text",
        "cross_owner_batch",
        "expired_commit",
        "tampered_token",
    }
    assert {case["operation"] for case in security["cases"]} == required_security
    manifest = load_json(DAY5_FIXTURE_ROOT / "g4_eval_manifest.json")
    assert manifest["split_algorithm"] == "g4_split_v1"
    assert [group["count"] for group in manifest["groups"]] == [24, 60, 12, 8]
    for group in manifest["groups"]:
        assert sum(source["count"] for source in group["sources"]) == group["count"]
        for source in group["sources"]:
            payload = (PROJECT_ROOT / source["path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == source["sha256"]


def validate_day6_g5_cases(
    api_schema: dict[str, Any], g5_llm_schema: dict[str, Any]
) -> None:
    semantic = load_json(DAY6_FIXTURE_ROOT / "semantic_cases.json")
    ab = load_json(DAY6_FIXTURE_ROOT / "ab_cases.json")
    examples = load_json(G5_EXAMPLES_PATH)
    for label, payload in (
        ("day6_semantic_cases", semantic),
        ("day6_ab_cases", ab),
        ("day6_g5_examples", examples),
    ):
        scan_forbidden(payload, label)

    for fixture in (semantic, ab):
        assert fixture["schema_version"] == "2.0.0"
        assert fixture["status"] == "member_b_real_gate_2026-08-30"
        assert fixture["provider_requirement"] == "real_only"

    semantic_cases = semantic["cases"]
    assert len(semantic_cases) == 16
    assert len({case["case_id"] for case in semantic_cases}) == 16
    assert all(
        re.fullmatch(r"g5-\d{2}-[a-z0-9-]+", case["case_id"]) for case in semantic_cases
    )
    allowed_kinds = {"preference", "rule", "experience"}
    allowed_operations = {"add", "update", "supersede", "coexist", "noop"}
    allowed_applicability = {
        "applicable",
        "current_instruction_override",
        "conflict",
        "irrelevant",
    }
    allowed_effect = {"applied", "violated", "not_observable", "unknown"}
    for case in semantic_cases:
        assert case["seed_turns"]
        assert all(turn["content"].strip() for turn in case["seed_turns"])
        assert case["probe"].strip()
        assert case["probe_memory_mode"] in {"on", "off"}
        assert set(case["allowed_kinds"]) <= allowed_kinds
        assert set(case["allowed_operations"]) <= allowed_operations
        assert set(case.get("required_operations", [])) <= set(
            case["allowed_operations"]
        )
        assert set(case["allowed_applicability"]) <= allowed_applicability
        assert set(case["allowed_effect"]) <= allowed_effect
        if not case["expected_injected"]:
            assert case["allowed_effect"] == []

    assert any(case["probe_memory_mode"] == "off" for case in semantic_cases)
    assert any(case.get("cross_owner_probe") for case in semantic_cases)
    assert any(case.get("security_case") for case in semantic_cases)
    assert any(
        "supersede" in case.get("required_operations", []) for case in semantic_cases
    )
    assert any(
        "coexist" in case.get("required_operations", []) for case in semantic_cases
    )
    assert any(
        not turn["content"].isascii()
        for case in semantic_cases
        for turn in case["seed_turns"]
    )
    assert any(
        turn["content"].isascii()
        for case in semantic_cases
        for turn in case["seed_turns"]
    )

    ab_cases = ab["cases"]
    assert len(ab_cases) == 8
    assert {case["case_id"] for case in ab_cases} == {
        f"ab-{index:02d}-{suffix}"
        for index, suffix in enumerate(
            (
                "concise",
                "bullets",
                "assumptions",
                "analogy",
                "table",
                "risks",
                "debug-timeline",
                "explain-before-code",
            ),
            start=1,
        )
    }
    assert all(
        case["memory"].strip() and case["probe"].strip() and case["criterion"].strip()
        for case in ab_cases
    )

    assert examples["schema_version"] == "2.0.0"
    assert examples["evidence_label"] == (
        "synthetic_contract_examples_not_semantic_evidence"
    )
    for example in examples["rest_requests"]:
        assert_valid(
            schema_validator(api_schema, example["definition"]),
            example["value"],
            f"day6-g5/rest/{example['definition']}",
        )
    for example in examples["llm_outputs"]:
        assert_valid(
            schema_validator(g5_llm_schema, example["definition"]),
            example["value"],
            f"day6-g5/llm/{example['definition']}",
        )


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
        "memory.retrieval.completed",
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
        "memory.retrieval.completed",
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
        "memory.retrieval.completed",
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
    g5_llm_schema = load_json(G5_LLM_SCHEMA_PATH)
    Draft202012Validator.check_schema(api_schema)
    Draft202012Validator.check_schema(event_schema)
    Draft202012Validator.check_schema(g5_llm_schema)
    event_validator = Draft202012Validator(event_schema, format_checker=FormatChecker())

    validate_demo_core(api_schema)
    validate_feedback_drafts()
    validate_day2_matrix()
    validate_day3_learning_events(api_schema)
    validate_day4_g3_cases()
    validate_day5_g4_cases()
    validate_day6_g5_cases(api_schema, g5_llm_schema)
    for path in MOCK_FIXTURES:
        validate_mock_fixture(path, api_schema, event_validator)

    print("PASS: both Draft 2020-12 schemas are structurally valid")
    print("PASS: 8 demo_core cases, 8 feedback drafts, and 24 Day 2 G1 matrix entries")
    print(
        "PASS: Day 3 learning events cover durability matrix, 0-3 candidates, "
        "provider failure paths, and zh/en feedback"
    )
    print("PASS: 30 owner-verified Day 4 G3 REST-only cases and privacy metadata")
    print("PASS: 8 Day 5 conflict and 12 Pack/security REST-only cases")
    print("PASS: 16 Day 6 real semantic and 8 blind A/B cases plus strict G5 examples")
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
