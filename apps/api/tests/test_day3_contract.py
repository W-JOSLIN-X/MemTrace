"""Day 3 G2 contract-lock tests: public models, events, JSON Schema, and Mock examples.

These tests freeze the shared contract before any implementation so member B can
build the UI against a stable shape and both sides fail loudly on drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from memtrace_api.config import PROJECT_ROOT
from memtrace_api.events import (
    PAYLOAD_TYPES,
    PERSISTENT_EVENT_TYPES,
    EventType,
    make_event,
)
from memtrace_api.schemas import (
    Disposition,
    MemoryCard,
    MemoryCardPatch,
    MemoryCardStatus,
    MemoryJobResponse,
    MemoryJobStage,
    ResolveAction,
    ResolveRequest,
    ScopeLevel,
    utc_now,
)

MEMORY_ID = "mem_01J00000000000000000000001"
MEMVER_ID = "memver_01J00000000000000000000001"
EVIDENCE_ID = "evidence_01J00000000000000000000001"
JOB_ID = "job_01J00000000000000000000001"
FEEDBACK_ID = "feedback_01J00000000000000000000001"
TASK_ID = "task_01J00000000000000000000001"
RUN_ID = "run_01J00000000000000000000001"
REQ_ID = "req_01J00000000000000000000001"


def _candidate_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "memory_id": MEMORY_ID,
        "kind": "preference",
        "title": "学习调试先提示",
        "rule": "先给一个可执行的诊断动作，再逐步增加提示。",
        "avoid": "首次回复直接给完整修复。",
        "trigger_text": "编程学习中的调试指导",
        "scope": {"level": "task_family", "domain": "programming_learning"},
        "exceptions": [],
        "status": "candidate",
        "source_type": "explicit_feedback",
        "save_preselected": True,
        "source_trust": 1.0,
        "rule_confidence": None,
        "scope_confidence": None,
        "evidence_count": 1,
        "version": 0,
        "current_version_id": None,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    values.update(overrides)
    return values


# --------------------------------------------------------------------------- #
# MemoryCard admission invariants
# --------------------------------------------------------------------------- #


def test_candidate_card_invariants() -> None:
    card = MemoryCard.model_validate(_candidate_values())
    assert card.status is MemoryCardStatus.CANDIDATE
    assert card.version == 0
    assert card.current_version_id is None
    assert card.rule_confidence is None
    assert card.scope_confidence is None


def test_candidate_card_cannot_carry_version_or_confidence() -> None:
    with pytest.raises(ValidationError):
        MemoryCard.model_validate(_candidate_values(version=1))
    with pytest.raises(ValidationError):
        MemoryCard.model_validate(_candidate_values(current_version_id=MEMVER_ID))
    with pytest.raises(ValidationError):
        MemoryCard.model_validate(_candidate_values(rule_confidence=0.9))
    with pytest.raises(ValidationError):
        MemoryCard.model_validate(_candidate_values(scope_confidence=0.9))


def test_active_card_requires_confirmed_version() -> None:
    with pytest.raises(ValidationError):
        MemoryCard.model_validate(_candidate_values(status="active"))
    active = MemoryCard.model_validate(
        _candidate_values(
            status="active",
            version=1,
            current_version_id=MEMVER_ID,
            rule_confidence=1.0,
            scope_confidence=1.0,
        )
    )
    assert active.status is MemoryCardStatus.ACTIVE
    assert active.current_version_id == MEMVER_ID


def test_explicit_durable_preselected_does_not_activate() -> None:
    card = MemoryCard.model_validate(_candidate_values(save_preselected=True, status="candidate"))
    assert card.status is MemoryCardStatus.CANDIDATE
    assert card.save_preselected is True


def test_scope_must_have_level_and_domain() -> None:
    with pytest.raises(ValidationError):
        MemoryCard.model_validate(_candidate_values(scope={"level": ScopeLevel.TASK_FAMILY.value}))


def test_memory_card_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        MemoryCard.model_validate(_candidate_values(owner_id="usr_01J00000000000000000000001"))


# --------------------------------------------------------------------------- #
# Resolve request rules
# --------------------------------------------------------------------------- #


def test_resolve_accept_rejects_patch() -> None:
    with pytest.raises(ValidationError):
        ResolveRequest(action=ResolveAction.ACCEPT, patch={"title": "改了标题"})


def test_resolve_edit_accept_requires_patch() -> None:
    with pytest.raises(ValidationError):
        ResolveRequest(action=ResolveAction.EDIT_ACCEPT)


def test_resolve_edit_accept_patch_forbids_kind_owner_status() -> None:
    patch = MemoryCardPatch(rule="这是一个长度至少二十个字符的修改后的规则正文内容。")
    with pytest.raises(ValidationError):
        ResolveRequest(
            action=ResolveAction.EDIT_ACCEPT,
            patch=MemoryCardPatch.model_validate({"kind": "preference"}),
        )
    # An empty patch is invalid on its own and as edit_accept's patch.
    with pytest.raises(ValidationError):
        MemoryCardPatch.model_validate({})
    assert patch.rule is not None


def test_resolve_reject_and_one_shot_allow_null_patch() -> None:
    for action in (ResolveAction.REJECT, ResolveAction.ONE_SHOT):
        req = ResolveRequest(action=action)
        assert req.patch is None


# --------------------------------------------------------------------------- #
# MemoryJob response shape
# --------------------------------------------------------------------------- #


def test_memory_job_response_g2_shape() -> None:
    job = MemoryJobResponse(
        request_id=REQ_ID,
        memory_job_id=JOB_ID,
        feedback_id=FEEDBACK_ID,
        status="completed",
        stage=MemoryJobStage.DONE,
        attempt=1,
        candidate_ids=[MEMORY_ID],
        disposition=Disposition.CANDIDATE_CREATED,
        error_code=None,
        retryable=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    assert job.feedback_id == FEEDBACK_ID
    assert job.candidate_ids == [MEMORY_ID]
    assert job.disposition is Disposition.CANDIDATE_CREATED
    assert job.error_code is None


def test_memory_job_response_rejects_more_than_three_candidates() -> None:
    with pytest.raises(ValidationError):
        MemoryJobResponse(
            request_id=REQ_ID,
            memory_job_id=JOB_ID,
            feedback_id=FEEDBACK_ID,
            status="completed",
            stage=MemoryJobStage.DONE,
            candidate_ids=[f"mem_01J0000000000000000000000{i:02d}" for i in range(1, 5)],
            disposition=Disposition.CANDIDATE_CREATED,
            created_at=utc_now(),
            updated_at=utc_now(),
        )


# --------------------------------------------------------------------------- #
# New event payloads
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        (
            EventType.MEMORY_EXTRACTION_STAGE,
            {"memory_job_id": JOB_ID, "stage": "extracting"},
        ),
        (
            EventType.MEMORY_CANDIDATE_CREATED,
            {
                "memory_job_id": JOB_ID,
                "memory_id": MEMORY_ID,
                "evidence_id": EVIDENCE_ID,
                "ordinal": 0,
            },
        ),
        (
            EventType.MEMORY_ADMISSION_RESOLVED,
            {
                "memory_id": MEMORY_ID,
                "old_status": "candidate",
                "new_status": "active",
                "memory_version_id": MEMVER_ID,
                "disposition": "candidate_created",
            },
        ),
        (
            EventType.MEMORY_JOB_FAILED,
            {
                "memory_job_id": JOB_ID,
                "stage": "extracting",
                "error_code": "MEMORY_JSON_INVALID",
                "retryable": True,
            },
        ),
    ],
)
def test_new_events_are_persistent_and_typed(
    event_type: EventType, data: dict[str, object]
) -> None:
    assert event_type in PERSISTENT_EVENT_TYPES
    assert PAYLOAD_TYPES[event_type] is not None
    envelope = make_event(
        event_type=event_type,
        event_seq=1,
        task_id=TASK_ID,
        run_id=RUN_ID,
        data=data,
    )
    assert envelope.event_seq == 1
    assert envelope.event_type is event_type


# --------------------------------------------------------------------------- #
# JSON Schema sync
# --------------------------------------------------------------------------- #

_EVENTS_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "schemas" / "events.schema.json"
_G0_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "schemas" / "g0-api.schema.json"


def _load_schema(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_events_schema_contains_all_persistent_event_types() -> None:
    schema = _load_schema(_EVENTS_SCHEMA_PATH)
    enum = schema["properties"]["event_type"]["enum"]
    for event_type in PERSISTENT_EVENT_TYPES:
        assert event_type.value in enum, event_type.value


def test_events_schema_validates_new_event_envelopes() -> None:
    schema = _load_schema(_EVENTS_SCHEMA_PATH)
    validator = jsonschema.Draft202012Validator(schema)
    for event_type, data in [
        (
            EventType.MEMORY_EXTRACTION_STAGE,
            {"memory_job_id": JOB_ID, "stage": "extracting"},
        ),
        (
            EventType.MEMORY_CANDIDATE_CREATED,
            {
                "memory_job_id": JOB_ID,
                "memory_id": MEMORY_ID,
                "evidence_id": EVIDENCE_ID,
                "ordinal": 1,
            },
        ),
        (
            EventType.MEMORY_ADMISSION_RESOLVED,
            {
                "memory_id": MEMORY_ID,
                "old_status": "candidate",
                "new_status": "rejected",
                "memory_version_id": None,
                "disposition": "episode_only",
            },
        ),
        (
            EventType.MEMORY_JOB_FAILED,
            {
                "memory_job_id": JOB_ID,
                "stage": "extracting",
                "error_code": "MEMORY_REPAIR_FAILED",
                "retryable": True,
            },
        ),
    ]:
        envelope = make_event(
            event_type=event_type,
            event_seq=3,
            task_id=TASK_ID,
            run_id=RUN_ID,
            data=data,
        )
        validator.validate(json.loads(envelope.model_dump_json()))


def test_g0_schema_rejects_resolve_kind_owner_status() -> None:
    schema = _load_schema(_G0_SCHEMA_PATH)
    resolver = jsonschema.Draft202012Validator(schema)
    patch = {"kind": "preference"}
    with pytest.raises(jsonschema.ValidationError):
        resolver.validate(
            {"action": "edit_accept", "patch": patch},
        )


def test_g0_schema_rejects_memory_job_extra_field() -> None:
    schema = _load_schema(_G0_SCHEMA_PATH)
    resolver = jsonschema.Draft202012Validator(schema)
    with pytest.raises(jsonschema.ValidationError):
        resolver.validate(
            {
                "request_id": REQ_ID,
                "memory_job_id": JOB_ID,
                "feedback_id": FEEDBACK_ID,
                "job_type": "extract_feedback",
                "status": "pending",
                "stage": "queued",
                "attempt": 0,
                "candidate_ids": [],
                "disposition": None,
                "error_code": None,
                "retryable": False,
                "created_at": "2026-08-23T00:00:00Z",
                "updated_at": "2026-08-23T00:00:00Z",
                "secret_field": "nope",
            }
        )


def test_audit_manifest_declares_new_events_and_endpoints() -> None:
    manifest = _load_schema(PROJECT_ROOT / "contracts" / "day3-g2.json")
    assert manifest["contract_version"] == "1.2.0"
    assert set(manifest["new_persistent_events"]) == {
        "memory.extraction.stage",
        "memory.candidate.created",
        "memory.admission.resolved",
        "memory.job.failed",
    }
    paths = {(e["method"], e["path"]) for e in manifest["new_endpoints"]}
    assert ("POST", "/api/v1/memory-jobs/{job_id}/retry") in paths
    assert ("POST", "/api/v1/memory-candidates/{memory_id}/resolve") in paths
    assert ("GET", "/api/v1/memories") in paths
    assert ("GET", "/api/v1/memories/{memory_id}") in paths


def test_mock_examples_match_schema() -> None:
    examples = _load_schema(PROJECT_ROOT / "contracts" / "examples" / "day3-g2.json")
    events_schema = _load_schema(_EVENTS_SCHEMA_PATH)
    validator = jsonschema.Draft202012Validator(events_schema)
    for example in examples["sse_examples"]:
        event_type = EventType(example["event"])
        envelope = make_event(
            event_type=event_type,
            event_seq=1,
            task_id=TASK_ID,
            run_id=RUN_ID,
            data=example["data"],
        )
        validator.validate(json.loads(envelope.model_dump_json()))
