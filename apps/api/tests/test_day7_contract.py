"""Day 7 public-release contract projection tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = PROJECT_ROOT / "contracts" / "schemas"

PUBLIC_ROOTS = {
    "AuthSessionResponse",
    "ConversationListResponse",
    "ImportCommitV2Response",
    "MemoryConflictResolveV2Response",
    "MemoryDeleteV2Response",
    "MemoryPackV2Document",
    "MemoryVersionDiffV2Response",
    "PackPreviewV2Response",
    "RegisterRequest",
    "RegisterResponse",
    "SourceTaskDeleteV2Response",
    "SystemResponse",
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


def test_day7_manifest_and_public_openapi_surface_are_frozen() -> None:
    manifest = json.loads((PROJECT_ROOT / "contracts" / "day7-release.json").read_text("utf-8"))
    assert manifest["contract_version"] == "2.1.0"
    assert manifest["database_head"] == "007_day7_public_release"
    assert manifest["authentication"]["demo_sessions_in_release"] is False
    assert manifest["semantic_authority"]["mock_semantic_acceptance_forbidden"] is True

    openapi = json.loads((PROJECT_ROOT / "contracts" / "openapi.json").read_text("utf-8"))
    expected_paths = {
        "/api/v2/auth/register",
        "/api/v2/auth/login",
        "/api/v2/auth/session",
        "/api/v2/auth/logout",
        "/api/v2/auth/logout-all",
        "/api/v2/auth/change-password",
        "/api/v2/auth/recover",
        "/api/v2/auth/recovery-code/rotate",
        "/api/v2/auth/account",
        "/api/v2/system",
        "/api/v2/tasks",
        "/api/v2/tasks/{task_id}/stream",
        "/api/v2/memories",
        "/api/v2/memories/{memory_id}",
        "/api/v2/memories/{memory_id}/version-diff",
        "/api/v2/memories/{memory_id}/versions/restore",
        "/api/v2/memories/{memory_id}/usages",
        "/api/v2/memories/{memory_id}/relations",
        "/api/v2/memory-conflicts",
        "/api/v2/memory-conflicts/{relation_id}/resolve",
        "/api/v2/memory-packs/export",
        "/api/v2/memory-packs/import/preview",
        "/api/v2/memory-packs/import/commit",
    }
    assert expected_paths <= set(openapi["paths"])
    authenticated_writes = {
        ("/api/v2/auth/logout", "post"),
        ("/api/v2/auth/logout-all", "post"),
        ("/api/v2/auth/change-password", "post"),
        ("/api/v2/auth/recovery-code/rotate", "post"),
        ("/api/v2/auth/account/preferences", "patch"),
        ("/api/v2/auth/account", "delete"),
    }
    for path, method in authenticated_writes:
        parameters = openapi["paths"][path][method]["parameters"]
        assert any(
            parameter.get("in") == "header" and parameter.get("name") == "Idempotency-Key"
            for parameter in parameters
        )


def test_day7_rest_definitions_match_actual_openapi_components() -> None:
    openapi = json.loads((PROJECT_ROOT / "contracts" / "openapi.json").read_text("utf-8"))
    normative = json.loads((SCHEMAS / "g0-api.schema.json").read_text("utf-8"))
    for name in PUBLIC_ROOTS:
        assert normative["$defs"][name] == _rewrite_refs(openapi["components"]["schemas"][name])


def test_day7_generated_definition_order_is_deterministic() -> None:
    pack_schema = json.loads((SCHEMAS / "memory-pack-v2.schema.json").read_text(encoding="utf-8"))
    assert list(pack_schema["$defs"]) == sorted(pack_schema["$defs"])


def test_day7_examples_validate_and_stream_text_is_transient_only() -> None:
    examples = json.loads(
        (PROJECT_ROOT / "contracts" / "examples" / "day7-release.json").read_text("utf-8")
    )
    rest = json.loads((SCHEMAS / "g0-api.schema.json").read_text("utf-8"))
    stream = json.loads((SCHEMAS / "conversation-events.schema.json").read_text("utf-8"))
    assert examples["schema_version"] == "2.1.0"
    for example in examples["rest_requests"]:
        validator = jsonschema.Draft202012Validator(
            {"$ref": f"#/$defs/{example['definition']}", "$defs": rest["$defs"]}
        )
        assert not list(validator.iter_errors(example["value"]))
    validator = jsonschema.Draft202012Validator(stream)
    for event in examples["conversation_events"]:
        assert not list(validator.iter_errors(event))
    invalid_persistent_text = {
        "event_type": "turn.completed",
        "event_seq": 2,
        "data": {
            **next(
                event["data"]
                for event in examples["conversation_events"]
                if event["event_type"] == "turn.completed"
            ),
            "assistant_text": "forbidden",
        },
    }
    assert list(validator.iter_errors(invalid_persistent_text))


def test_memory_pack_v2_schema_is_strict_and_forbids_local_identity_fields() -> None:
    schema = json.loads((SCHEMAS / "memory-pack-v2.schema.json").read_text("utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    document = schema["$defs"]["MemoryPackV2Document"]
    assert document["additionalProperties"] is False
    card = schema["$defs"]["MemoryPackV2Card"]
    assert card["additionalProperties"] is False
    assert "owner_id" not in card["properties"]
    assert "memory_id" not in card["properties"]
    assert "task_id" not in card["properties"]
    assert "evidence" not in card["properties"]
