"""Project the exported G4 OpenAPI models into the normative REST-body schema."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "contracts/openapi.json"
TARGET = ROOT / "contracts/schemas/g0-api.schema.json"

G4_ROOTS = {
    "MemoryDeleteRequest",
    "MemoryDeleteResponse",
    "TaskDeleteRequest",
    "TaskDeleteResponse",
    "MemoryRelationListResponse",
    "MemoryVersionDiffResponse",
    "MemoryConflictDetailResponse",
    "MemoryConflictDetectRequest",
    "MemoryConflictDetectResponse",
    "MemoryConflictResolveRequest",
    "MemoryConflictResolveResponse",
    "MemoryMergeRequest",
    "MemoryMergeResponse",
    "PackExportRequest",
    "MemoryPackDocument",
    "PackPreviewResponse",
    "ImportCommitRequest",
    "ImportCommitResponse",
    "ImportBatchResponse",
}


def referenced_names(value: Any) -> set[str]:
    rendered = json.dumps(value)
    return set(re.findall(r"#/components/schemas/([A-Za-z0-9_]+)", rendered))


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


def main() -> None:
    openapi = json.loads(OPENAPI.read_text(encoding="utf-8"))
    target = json.loads(TARGET.read_text(encoding="utf-8"))
    components = openapi["components"]["schemas"]
    pending = list(G4_ROOTS)
    while pending:
        name = pending.pop()
        if name in target["$defs"]:
            continue
        schema = components[name]
        target["$defs"][name] = rewrite_refs(schema)
        pending.extend(referenced_names(schema) - set(target["$defs"]))
    existing = {item["$ref"] for item in target["oneOf"]}
    for name in sorted(G4_ROOTS):
        ref = f"#/$defs/{name}"
        if ref not in existing:
            target["oneOf"].append({"$ref": ref})
    target["description"] = "Normative MemTrace G1-G4 REST request and response bodies."
    TARGET.write_text(
        json.dumps(target, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
