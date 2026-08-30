"""Project deterministic G5 REST and structured-LLM schemas into contracts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "apps" / "api"
OPENAPI = ROOT / "contracts" / "openapi.json"
REST_TARGET = ROOT / "contracts" / "schemas" / "g0-api.schema.json"
LLM_TARGET = ROOT / "contracts" / "schemas" / "g5-llm.schema.json"

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


def referenced_names(value: Any, prefix: str) -> set[str]:
    rendered = json.dumps(value)
    return set(re.findall(re.escape(prefix) + r"([A-Za-z0-9_]+)", rendered))


def rewrite_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                item.replace("#/components/schemas/", "#/$defs/")
                if key == "$ref" and isinstance(item, str)
                else rewrite_refs(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [rewrite_refs(item) for item in value]
    return value


def sync_rest() -> None:
    openapi = json.loads(OPENAPI.read_text(encoding="utf-8"))
    target = json.loads(REST_TARGET.read_text(encoding="utf-8"))
    components = openapi["components"]["schemas"]
    pending = list(G5_REST_ROOTS)
    visited: set[str] = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        schema = components[name]
        # G5-owned names are refreshed from the actual application. Shared
        # legacy definitions stay untouched unless they do not exist yet.
        if name in G5_REST_ROOTS or name not in target["$defs"]:
            target["$defs"][name] = rewrite_refs(schema)
        pending.extend(referenced_names(schema, "#/components/schemas/") - visited)
    existing = {item["$ref"] for item in target["oneOf"]}
    for name in sorted(G5_REST_ROOTS):
        ref = f"#/$defs/{name}"
        if ref not in existing:
            target["oneOf"].append({"$ref": ref})
    target["description"] = "Normative MemTrace G1-G5 REST request and response bodies."
    REST_TARGET.write_text(
        json.dumps(target, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sync_llm() -> None:
    sys.path.insert(0, str(API_ROOT / "src"))
    from memtrace_api.schemas import (
        ApplicabilityJudgeWireResult,
        ConflictConsolidationWireResult,
        EffectJudgeWireResult,
        MemoryMutationBatch,
        RollingSummaryWireResult,
    )

    models = {
        "MemoryMutationBatch": MemoryMutationBatch,
        "ApplicabilityJudgeWireResult": ApplicabilityJudgeWireResult,
        "ConflictConsolidationWireResult": ConflictConsolidationWireResult,
        "EffectJudgeWireResult": EffectJudgeWireResult,
        "RollingSummaryWireResult": RollingSummaryWireResult,
    }
    definitions: dict[str, Any] = {}
    roots: list[dict[str, str]] = []
    for name, model in models.items():
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        definitions.update(schema.pop("$defs", {}))
        definitions[name] = schema
        roots.append({"$ref": f"#/$defs/{name}"})
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://memtrace.local/contracts/schemas/g5-llm.schema.json",
        "title": "MemTrace G5 strict structured LLM outputs",
        "description": (
            "Normative provider wire schemas. Unknown fields are rejected and "
            "semantic failures never fall back to keywords or Mock output."
        ),
        "oneOf": roots,
        "$defs": definitions,
    }
    LLM_TARGET.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    sync_rest()
    sync_llm()
    print(REST_TARGET)
    print(LLM_TARGET)


if __name__ == "__main__":
    main()
