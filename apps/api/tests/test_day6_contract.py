"""Day 6 contract projection and persistent-event tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from memtrace_api.events import EventType, make_event

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = PROJECT_ROOT / "contracts" / "schemas"
ID = "01J00000000000000000000001"
G5_REST_ROOTS = {
    "ConsolidationJudgmentProjection",
    "ConversationTaskCreateRequest",
    "ConversationTaskCreateResponse",
    "ConversationTaskSnapshotResponse",
    "ConversationTurnRequest",
    "ConversationTurnResponse",
    "ConversationTurnStateProjection",
    "MemoryConfirmResponse",
    "MemoryDetailV2Response",
    "MemoryDismissResponse",
    "MemoryEventListResponse",
    "MemoryFeedbackRequest",
    "MemoryFeedbackResponse",
    "MemoryLifecycleV2Response",
    "MemoryReflectionJobResponse",
    "MemoryV2EditRequest",
    "MemoryV2EditResponse",
    "MemoryV2ListResponse",
    "StageUsageProjection",
    "TaskMemoryUsageResponse",
}


def _rewrite_refs(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: (
                item.replace("#/components/schemas/", "#/$defs/")
                if key == "$ref" and isinstance(item, str)
                else _rewrite_refs(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_refs(item) for item in value]
    return value


def test_g5_rest_definitions_match_actual_openapi_components() -> None:
    openapi = json.loads((PROJECT_ROOT / "contracts" / "openapi.json").read_text("utf-8"))
    normative = json.loads((SCHEMAS / "g0-api.schema.json").read_text("utf-8"))
    for name in G5_REST_ROOTS:
        assert normative["$defs"][name] == _rewrite_refs(openapi["components"]["schemas"][name])
    assert normative["description"] == (
        "Normative MemTrace G1-G5 and Day 7 public-release REST request and response bodies."
    )


def test_g5_openapi_contains_complete_public_routes() -> None:
    document = json.loads((PROJECT_ROOT / "contracts" / "openapi.json").read_text("utf-8"))
    paths = document["paths"]
    expected = {
        "/api/v2/tasks",
        "/api/v2/tasks/{task_id}/turns",
        "/api/v2/tasks/{task_id}",
        "/api/v2/tasks/{task_id}/events",
        "/api/v2/memories",
        "/api/v2/memories/{memory_id}",
        "/api/v2/memories/{memory_id}/confirm",
        "/api/v2/memories/{memory_id}/dismiss",
        "/api/v2/memories/{memory_id}/pause",
        "/api/v2/memories/{memory_id}/resume",
        "/api/v2/memories/{memory_id}/events",
        "/api/v2/memory-events",
        "/api/v2/reflection-jobs/{job_id}",
        "/api/v2/reflection-jobs/{job_id}/usage",
        "/api/v2/reflection-jobs/{job_id}/judgments",
        "/api/v2/tasks/{task_id}/memory-usage",
        "/api/v2/tasks/{task_id}/memory-effect/{memory_id}/feedback",
    }
    assert expected <= set(paths)


def test_g5_structured_llm_schema_is_strict_and_rejects_unknown_fields() -> None:
    schema = json.loads((SCHEMAS / "g5-llm.schema.json").read_text("utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    extraction = {
        "schema_version": "2.0",
        "decision": "noop",
        "operations": [],
    }
    validator = jsonschema.Draft202012Validator(
        {"$ref": "#/$defs/MemoryMutationBatch", "$defs": schema["$defs"]}
    )
    assert not list(validator.iter_errors(extraction))
    assert list(validator.iter_errors({**extraction, "keyword_fallback": True}))
    assert schema["$defs"]["ApplicabilityJudgeWireResult"]["additionalProperties"] is False
    assert schema["$defs"]["RollingSummaryWireResult"]["additionalProperties"] is False


def test_g5_examples_validate_against_normative_schemas() -> None:
    examples = json.loads(
        (PROJECT_ROOT / "contracts" / "examples" / "day6-g5.json").read_text("utf-8")
    )
    rest_schema = json.loads((SCHEMAS / "g0-api.schema.json").read_text("utf-8"))
    llm_schema = json.loads((SCHEMAS / "g5-llm.schema.json").read_text("utf-8"))
    assert examples["schema_version"] == "2.0.0"
    assert examples["evidence_label"] == ("synthetic_contract_examples_not_semantic_evidence")
    for example in examples["rest_requests"]:
        validator = jsonschema.Draft202012Validator(
            {
                "$ref": f"#/$defs/{example['definition']}",
                "$defs": rest_schema["$defs"],
            }
        )
        assert not list(validator.iter_errors(example["value"]))
    for example in examples["llm_outputs"]:
        validator = jsonschema.Draft202012Validator(
            {
                "$ref": f"#/$defs/{example['definition']}",
                "$defs": llm_schema["$defs"],
            }
        )
        assert not list(validator.iter_errors(example["value"]))


def test_g5_persistent_event_payloads_match_python_and_json_schema() -> None:
    schema = json.loads((SCHEMAS / "events.schema.json").read_text("utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    task_id = f"task_{ID}"
    run_id = f"run_{ID}"
    job_id = f"job_{ID}"
    memory_id = f"mem_{ID}"
    examples = [
        make_event(
            event_type=EventType.MEMORY_ANALYSIS_STARTED,
            event_seq=1,
            task_id=task_id,
            run_id=run_id,
            data={
                "job_id": job_id,
                "task_id": task_id,
                "run_id": run_id,
                "status": "running",
            },
        ),
        make_event(
            event_type=EventType.MEMORY_ANALYSIS_COMPLETED,
            event_seq=2,
            task_id=task_id,
            run_id=run_id,
            data={
                "job_id": job_id,
                "task_id": task_id,
                "run_id": run_id,
                "status": "completed",
                "reason_code": "mutate",
            },
        ),
        make_event(
            event_type=EventType.MEMORY_EFFECT_JUDGED,
            event_seq=3,
            task_id=task_id,
            run_id=run_id,
            data={
                "memory_id": memory_id,
                "run_id": run_id,
                "judgment": "applied",
                "reason_code": "followed",
            },
        ),
    ]
    for event in examples:
        payload = event.model_dump(mode="json")
        assert not list(validator.iter_errors(payload))
