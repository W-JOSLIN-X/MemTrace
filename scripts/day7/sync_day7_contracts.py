"""Project the Day 7 public REST, Pack v2, and task-stream contracts.

The actual FastAPI OpenAPI document is the source for request/response models.
The task stream is projected separately because SSE frames are not OpenAPI JSON
response bodies.  This script is deterministic and safe to run repeatedly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "contracts" / "openapi.json"
REST_TARGET = ROOT / "contracts" / "schemas" / "g0-api.schema.json"
PACK_TARGET = ROOT / "contracts" / "schemas" / "memory-pack-v2.schema.json"
STREAM_TARGET = ROOT / "contracts" / "schemas" / "conversation-events.schema.json"

PUBLIC_REST_ROOTS = {
    "AccountPreferencesRequest",
    "AccountProjection",
    "AuthActionResponse",
    "AuthSessionResponse",
    "ChangePasswordRequest",
    "ConversationListResponse",
    "ConversationTaskCreateRequest",
    "ConversationTaskCreateResponse",
    "ConversationTaskSnapshotResponse",
    "ConversationTurnRequest",
    "ConversationTurnResponse",
    "DeleteAccountRequest",
    "ErrorCode",
    "ErrorEnvelope",
    "ImportCommitRequest",
    "ImportCommitV2Response",
    "LoginRequest",
    "MemoryConflictDetailV2Response",
    "MemoryConflictDetectV2Request",
    "MemoryConflictDetectV2Response",
    "MemoryConflictResolveV2Request",
    "MemoryConflictResolveV2Response",
    "MemoryDeleteV2Request",
    "MemoryDeleteV2Response",
    "MemoryDetailV2Response",
    "MemoryEventListResponse",
    "MemoryFeedbackRequest",
    "MemoryFeedbackResponse",
    "MemoryLifecycleV2Response",
    "MemoryPackV2Document",
    "MemoryReflectionJobResponse",
    "MemoryRelationV2ListResponse",
    "MemoryUsageV2ListResponse",
    "MemoryV2EditRequest",
    "MemoryV2EditResponse",
    "MemoryV2ListResponse",
    "MemoryVersionDiffV2Response",
    "MemoryVersionRestoreV2Request",
    "PackExportV2Request",
    "PackPreviewV2Response",
    "RecoverRequest",
    "RecoveryCodeResponse",
    "RecoveryResponse",
    "RegisterRequest",
    "RegisterResponse",
    "SourceTaskDeleteV2Request",
    "SourceTaskDeleteV2Response",
    "SystemResponse",
}


def _referenced_names(value: Any) -> set[str]:
    return set(re.findall(r"#/components/schemas/([A-Za-z0-9_]+)", json.dumps(value)))


def _rewrite_refs(value: Any) -> Any:
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


def _collect(components: dict[str, Any], roots: set[str]) -> dict[str, Any]:
    pending = list(roots)
    definitions: dict[str, Any] = {}
    while pending:
        name = pending.pop()
        if name in definitions:
            continue
        schema = components[name]
        definitions[name] = _rewrite_refs(schema)
        pending.extend(_referenced_names(schema) - definitions.keys())
    return definitions


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _sync_rest(components: dict[str, Any]) -> None:
    target = json.loads(REST_TARGET.read_text(encoding="utf-8"))
    definitions = _collect(components, PUBLIC_REST_ROOTS)
    target["$defs"].update(definitions)
    existing = {item["$ref"] for item in target["oneOf"]}
    for name in sorted(PUBLIC_REST_ROOTS):
        ref = f"#/$defs/{name}"
        if ref not in existing:
            target["oneOf"].append({"$ref": ref})
    target["title"] = "MemTrace 2.1.0 REST bodies"
    target["description"] = (
        "Normative MemTrace G1-G5 and Day 7 public-release REST request and response bodies."
    )
    _write(REST_TARGET, target)


def _sync_pack(components: dict[str, Any]) -> None:
    definitions = _collect(components, {"MemoryPackV2Document"})
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://memtrace.local/contracts/schemas/memory-pack-v2.schema.json",
        "title": "MemTrace Memory Pack v2",
        "description": (
            "Anonymous, integrity-protected Memory Pack used by the Day 7 public v2 API. "
            "Local owner, task, message, evidence, and memory identifiers are forbidden."
        ),
        "$ref": "#/$defs/MemoryPackV2Document",
        "$defs": definitions,
    }
    _write(PACK_TARGET, document)


def _id_ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/$defs/{name}"}


def _event_variant(
    event_type: str, data: dict[str, Any], *, persistent: bool
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "event_type": {"const": event_type},
            "event_seq": {"type": "integer", "minimum": 1}
            if persistent
            else {"type": "null"},
            "data": data,
        },
        "required": ["event_type", "event_seq", "data"],
        "additionalProperties": False,
    }


def _sync_stream(components: dict[str, Any]) -> None:
    definitions = _collect(components, {"AsyncErrorCode"})
    definitions.update(
        {
            "RunId": {"type": "string", "pattern": r"^run_[0-9A-HJKMNP-TV-Z]{26}$"},
            "MessageId": {"type": "string", "pattern": r"^msg_[0-9A-HJKMNP-TV-Z]{26}$"},
            "MemoryReflectionJobId": {
                "type": "string",
                "pattern": r"^job_[0-9A-HJKMNP-TV-Z]{26}$",
            },
            "AssistantDeltaData": {
                "type": "object",
                "properties": {
                    "run_id": _id_ref("RunId"),
                    "delta_index": {"type": "integer", "minimum": 1},
                    "delta": {"type": "string", "minLength": 1, "maxLength": 32768},
                },
                "required": ["run_id", "delta_index", "delta"],
                "additionalProperties": False,
            },
            "TurnStartedData": {
                "type": "object",
                "properties": {
                    "event_seq": {"type": "integer", "minimum": 1},
                    "run_id": _id_ref("RunId"),
                    "turn_index": {"type": "integer", "minimum": 1},
                    "user_message_id": _id_ref("MessageId"),
                },
                "required": ["event_seq", "run_id", "turn_index", "user_message_id"],
                "additionalProperties": False,
            },
            "TurnCompletedData": {
                "type": "object",
                "properties": {
                    "event_seq": {"type": "integer", "minimum": 1},
                    "run_id": _id_ref("RunId"),
                    "turn_index": {"type": "integer", "minimum": 1},
                    "user_message_id": _id_ref("MessageId"),
                    "assistant_message_id": _id_ref("MessageId"),
                    "reflection_pending": {"type": "boolean"},
                    "job_id": {
                        "anyOf": [_id_ref("MemoryReflectionJobId"), {"type": "null"}]
                    },
                },
                "required": [
                    "event_seq",
                    "run_id",
                    "turn_index",
                    "user_message_id",
                    "assistant_message_id",
                    "reflection_pending",
                    "job_id",
                ],
                "additionalProperties": False,
            },
            "TurnFailedData": {
                "type": "object",
                "properties": {
                    "event_seq": {"type": "integer", "minimum": 1},
                    "run_id": _id_ref("RunId"),
                    "turn_index": {
                        "anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]
                    },
                    "error_code": _id_ref("AsyncErrorCode"),
                },
                "required": ["event_seq", "run_id", "turn_index", "error_code"],
                "additionalProperties": False,
            },
            "ToolSkippedData": {
                "type": "object",
                "properties": {
                    "event_seq": {"type": "integer", "minimum": 1},
                    "run_id": _id_ref("RunId"),
                    "turn_index": {"type": "integer", "minimum": 1},
                    "action": {"const": "skip"},
                    "reason_code": {"const": "model_skipped_tool"},
                    "model": {"type": "string", "minLength": 1, "maxLength": 128},
                    "input_tokens": {"type": "integer", "minimum": 0},
                    "output_tokens": {"type": "integer", "minimum": 0},
                    "total_tokens": {"type": "integer", "minimum": 0},
                    "provider_latency_ms": {"type": "number", "minimum": 0},
                },
                "required": [
                    "event_seq",
                    "run_id",
                    "turn_index",
                    "action",
                    "reason_code",
                    "model",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "provider_latency_ms",
                ],
                "additionalProperties": False,
            },
            "ToolCompletedData": {
                "type": "object",
                "properties": {
                    "event_seq": {"type": "integer", "minimum": 1},
                    "run_id": _id_ref("RunId"),
                    "turn_index": {"type": "integer", "minimum": 1},
                    "action": {"const": "call"},
                    "reason_code": {"const": "model_selected_allowed_tool"},
                    "model": {"type": "string", "minLength": 1, "maxLength": 128},
                    "input_tokens": {"type": "integer", "minimum": 0},
                    "output_tokens": {"type": "integer", "minimum": 0},
                    "total_tokens": {"type": "integer", "minimum": 0},
                    "provider_latency_ms": {"type": "number", "minimum": 0},
                    "tool_name": {"const": "python_ast_check"},
                    "tool_call_id": {
                        "type": "string",
                        "pattern": r"^tool_[0-9A-HJKMNP-TV-Z]{26}$",
                    },
                    "status": {"const": "succeeded"},
                    "code_source": {
                        "enum": ["fenced_python", "whole_task_valid_python"]
                    },
                    "code_bytes": {"type": "integer", "minimum": 1, "maximum": 102400},
                    "valid": {"type": "boolean"},
                    "latency_ms": {"type": "number", "minimum": 0},
                    "result_ref": {
                        "type": "string",
                        "pattern": r"^toolres_[0-9A-HJKMNP-TV-Z]{26}$",
                    },
                },
                "required": [
                    "event_seq",
                    "run_id",
                    "turn_index",
                    "action",
                    "reason_code",
                    "model",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "provider_latency_ms",
                    "tool_name",
                    "tool_call_id",
                    "status",
                    "code_source",
                    "code_bytes",
                    "valid",
                    "latency_ms",
                    "result_ref",
                ],
                "additionalProperties": False,
            },
        }
    )
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://memtrace.local/contracts/schemas/conversation-events.schema.json",
        "title": "MemTrace Day 7 decoded conversation SSE events",
        "description": (
            "Decoded SSE event name, persistent cursor, and data. assistant.delta is transient "
            "and must never be written to the persistent event log."
        ),
        "oneOf": [
            _event_variant(
                "assistant.delta", _id_ref("AssistantDeltaData"), persistent=False
            ),
            _event_variant("turn.started", _id_ref("TurnStartedData"), persistent=True),
            _event_variant(
                "turn.completed", _id_ref("TurnCompletedData"), persistent=True
            ),
            _event_variant("turn.failed", _id_ref("TurnFailedData"), persistent=True),
            _event_variant(
                "conversation.tool.skipped",
                _id_ref("ToolSkippedData"),
                persistent=True,
            ),
            _event_variant(
                "conversation.tool.completed",
                _id_ref("ToolCompletedData"),
                persistent=True,
            ),
        ],
        "$defs": definitions,
    }
    _write(STREAM_TARGET, document)


def main() -> None:
    openapi = json.loads(OPENAPI.read_text(encoding="utf-8"))
    components = openapi["components"]["schemas"]
    _sync_rest(components)
    _sync_pack(components)
    _sync_stream(components)
    print(REST_TARGET)
    print(PACK_TARGET)
    print(STREAM_TARGET)


if __name__ == "__main__":
    main()
