"""Contract tests: G4 contract file, day5-g4.json, memory-pack.schema.json exist and are valid."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import rfc8785

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = PROJECT_ROOT / "contracts"
SCHEMAS_DIR = CONTRACTS_DIR / "schemas"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"


def test_day5_g4_contract_exists() -> None:
    path = CONTRACTS_DIR / "day5-g4.json"
    assert path.exists(), f"Missing contract file: {path}"


def test_day5_g4_contract_valid_json() -> None:
    path = CONTRACTS_DIR / "day5-g4.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["contract_version"] == "1.4.0"
    assert data["gate"] == "G4"


def test_day5_g4_contract_references_schemas() -> None:
    data = json.loads((CONTRACTS_DIR / "day5-g4.json").read_text(encoding="utf-8"))
    refs = data["normative_contracts"]
    assert "memory_pack_schema" in refs
    pack_schema_path = SCHEMAS_DIR / "memory-pack.schema.json"
    assert pack_schema_path.exists(), f"Missing: {pack_schema_path}"


def test_day5_g4_example_exists() -> None:
    path = EXAMPLES_DIR / "day5-g4.json"
    assert path.exists(), f"Missing example: {path}"


def test_day5_g4_example_valid_json() -> None:
    data = json.loads((EXAMPLES_DIR / "day5-g4.json").read_text(encoding="utf-8"))
    assert data["schema_ref"] == "memtrace-memory-pack@1.0.0"
    assert data["format"] == "memtrace-memory-pack"
    assert len(data["cards"]) >= 1
    schema = json.loads((SCHEMAS_DIR / "memory-pack.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        data
    )
    expected = data["integrity"]["canonical_payload_sha256"]
    payload = {key: value for key, value in data.items() if key != "integrity"}
    assert hashlib.sha256(rfc8785.dumps(payload)).hexdigest() == expected


def test_g0_api_schema_has_g4_error_codes() -> None:
    schema = json.loads((SCHEMAS_DIR / "g0-api.schema.json").read_text(encoding="utf-8"))
    error_codes = schema["$defs"]["ErrorCode"]["enum"]
    required = {
        "MEMORY_RELATION_NOT_FOUND",
        "MEMORY_CONFLICT_ALREADY_RESOLVED",
        "MEMORY_MERGE_CONFLICT",
        "CONFIRMATION_MISMATCH",
        "MEMORY_PACK_TOO_LARGE",
        "MEMORY_PACK_INVALID",
        "MEMORY_PACK_UNSUPPORTED_VERSION",
        "MEMORY_PACK_INTEGRITY_MISMATCH",
        "IMPORT_BATCH_NOT_FOUND",
        "IMPORT_BATCH_EXPIRED",
        "IMPORT_PREVIEW_TOKEN_INVALID",
        "IMPORT_BATCH_STATE_CONFLICT",
        "INVALID_CURSOR",
    }
    missing = required - set(error_codes)
    assert not missing, f"Missing G4 error codes from g0-api.schema.json: {missing}"


def test_events_schema_has_g4_event_types() -> None:
    schema = json.loads((SCHEMAS_DIR / "events.schema.json").read_text(encoding="utf-8"))
    enum = schema["properties"]["event_type"]["enum"]
    required = {
        "task.deleted",
        "memory.lifecycle.changed",
        "memory.conflict.detected",
        "memory.conflict.resolved",
        "memory.pack.previewed",
        "memory.pack.committed",
    }
    missing = required - set(enum)
    assert not missing, f"Missing G4 event types from events.schema.json: {missing}"
    payload_defs = {
        "TaskDeletedPayload",
        "MemoryLifecyclePayload",
        "MemoryConflictDetectedPayload",
        "MemoryConflictResolvedPayload",
        "MemoryPackPreviewedPayload",
        "MemoryPackCommittedPayload",
    }
    assert payload_defs <= set(schema["$defs"])


def test_g0_api_schema_projects_g4_models() -> None:
    schema = json.loads((SCHEMAS_DIR / "g0-api.schema.json").read_text(encoding="utf-8"))
    required = {
        "MemoryDeleteRequest",
        "MemoryDeleteResponse",
        "TaskDeleteRequest",
        "TaskDeleteResponse",
        "MemoryRelationListResponse",
        "MemoryVersionDiffResponse",
        "MemoryConflictDetailResponse",
        "MemoryConflictDetectRequest",
        "MemoryConflictResolveRequest",
        "MemoryMergeRequest",
        "MemoryPackDocument",
        "PackPreviewResponse",
        "ImportCommitRequest",
        "ImportBatchResponse",
    }
    assert required <= set(schema["$defs"])


def test_memory_pack_schema_is_valid_json_schema() -> None:
    path = SCHEMAS_DIR / "memory-pack.schema.json"
    assert path.exists(), f"Missing: {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert data.get("title") == "MemTrace Memory Pack V1"
