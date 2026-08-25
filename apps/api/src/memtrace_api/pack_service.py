"""Strict Memory Pack parsing, validation, and privacy-safe classification."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

from memtrace_api.retrieval import (
    build_memory_document,
    compute_tfidf_vectors,
    cosine_similarity,
)

MAX_PACK_SIZE = 1_048_576
MAX_CARDS = 200
MAX_DEPTH = 12
MAX_SCALAR_NODES = 10_000
MAX_STRING = 10_000

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[4] / "contracts" / "schemas" / "memory-pack.schema.json"
)
_FORBIDDEN_KEYS = {
    "allowed_tools",
    "api_key",
    "command",
    "executable",
    "role",
    "script",
    "system_prompt",
    "tool",
    "tools",
    "url_fetch",
    "token",
    "secret",
}
_SUSPICIOUS_TEXT = re.compile(
    r"(?i)(<\s*script\b|javascript\s*:|data\s*:\s*text/html|on(?:error|load)\s*=|"
    r"ignore\s+(?:all\s+)?previous\s+instructions|system\s+prompt|BEGIN\s+(?:RSA|OPENSSH)\s+PRIVATE\s+KEY)"
)


class PackValidationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PackPreviewAnalysis:
    pack: dict[str, Any]
    canonical_json: str
    file_hash: str
    items: list[dict[str, Any]]

    @property
    def counts(self) -> dict[str, int]:
        return {
            name: sum(item["classification"] == name for item in self.items)
            for name in ("legal_new", "duplicate", "potential_conflict", "suspicious")
        }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PackValidationError("MEMORY_PACK_INVALID", "JSON 包含重复对象键。")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise PackValidationError("MEMORY_PACK_INVALID", f"JSON 数值 {value} 不受支持。")


def _inspect_tree(value: Any, *, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    if depth > MAX_DEPTH:
        raise PackValidationError("MEMORY_PACK_INVALID", "Pack 嵌套深度超过限制。")
    if isinstance(value, str):
        counter[0] += 1
        if counter[0] > MAX_SCALAR_NODES:
            raise PackValidationError("MEMORY_PACK_INVALID", "Pack scalar 节点数量超过限制。")
        if len(value) > MAX_STRING:
            raise PackValidationError("MEMORY_PACK_INVALID", "Pack 字符串长度超过限制。")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in _FORBIDDEN_KEYS:
                raise PackValidationError("MEMORY_PACK_INVALID", "Pack 包含禁止字段。")
            _inspect_tree(child, depth=depth + 1, counter=counter)
    elif isinstance(value, list):
        for child in value:
            _inspect_tree(child, depth=depth + 1, counter=counter)
    else:
        counter[0] += 1
        if counter[0] > MAX_SCALAR_NODES:
            raise PackValidationError("MEMORY_PACK_INVALID", "Pack scalar 节点数量超过限制。")


def _validate_relations(pack: dict[str, Any]) -> set[str]:
    ids = [card["external_id"] for card in pack["cards"]]
    if len(ids) != len(set(ids)):
        raise PackValidationError("MEMORY_PACK_INVALID", "Pack 卡片 external_id 必须唯一。")
    known = set(ids)
    seen: set[tuple[str, str, str]] = set()
    explicit_conflicts: set[str] = set()
    for relation in pack["relations"]:
        source = relation["from_external_id"]
        target = relation["to_external_id"]
        relation_type = relation["relation_type"]
        if source not in known or target not in known:
            raise PackValidationError("MEMORY_PACK_INVALID", "Pack 关系存在悬空引用。")
        if source == target:
            raise PackValidationError("MEMORY_PACK_INVALID", "Pack 关系不得自引用。")
        key = (source, target, relation_type)
        if key in seen:
            raise PackValidationError("MEMORY_PACK_INVALID", "Pack 包含重复关系。")
        seen.add(key)
        if relation_type == "conflicts_with":
            explicit_conflicts.update((source, target))
    return explicit_conflicts


def _scope_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for field in (
        "domain",
        "task_type",
        "artifact_type",
        "audience",
        "project_key",
        "language",
        "framework",
    ):
        left_value = left.get(field)
        right_value = right.get(field)
        if left_value not in (None, "any") and right_value not in (None, "any"):
            if left_value != right_value:
                return False
    return True


def _card_fingerprint(card: dict[str, Any]) -> str:
    projected = {
        key: card.get(key)
        for key in ("kind", "rule", "avoid", "trigger_text", "scope", "exceptions")
    }
    return hashlib.sha256(rfc8785.dumps(projected)).hexdigest()


def _card_document(card: dict[str, Any]) -> str:
    scope = card.get("scope") or {}
    return build_memory_document(
        SimpleNamespace(
            title=card.get("title") or "",
            rule=card.get("rule") or "",
            avoid=card.get("avoid") or "",
            trigger_text=card.get("trigger_text") or "",
            scope_json=json.dumps(scope, ensure_ascii=False, separators=(",", ":")),
            exceptions_json=json.dumps(card.get("exceptions") or [], ensure_ascii=False),
        )
    )


def _contains_suspicious_text(card: dict[str, Any]) -> bool:
    values = [
        card.get("title", ""),
        card.get("rule", ""),
        card.get("avoid", ""),
        card.get("trigger_text", ""),
        *(card.get("exceptions") or []),
    ]
    return any(_SUSPICIOUS_TEXT.search(value) for value in values if isinstance(value, str))


def parse_pack_bytes(raw: bytes) -> tuple[dict[str, Any], str, str]:
    if len(raw) > MAX_PACK_SIZE:
        raise PackValidationError(
            "MEMORY_PACK_TOO_LARGE", "Memory Pack 超过 1 MiB 限制。", status_code=413
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackValidationError("MEMORY_PACK_INVALID", "Memory Pack 必须使用 UTF-8。") from exc
    try:
        pack = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except PackValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PackValidationError("MEMORY_PACK_INVALID", "Memory Pack 不是有效 JSON。") from exc
    if not isinstance(pack, dict):
        raise PackValidationError("MEMORY_PACK_INVALID", "Memory Pack 根节点必须是对象。")
    _inspect_tree(pack)
    if (
        pack.get("schema_ref") != "memtrace-memory-pack@1.0.0"
        or pack.get("format") != "memtrace-memory-pack"
        or pack.get("format_version") != "1.0.0"
    ):
        raise PackValidationError(
            "MEMORY_PACK_UNSUPPORTED_VERSION", "仅支持 memtrace-memory-pack@1.0.0。"
        )
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(pack),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise PackValidationError("MEMORY_PACK_INVALID", "Memory Pack 不符合冻结 Schema。")
    _validate_relations(pack)
    payload = {key: value for key, value in pack.items() if key != "integrity"}
    actual_hash = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    if pack["integrity"]["canonical_payload_sha256"] != actual_hash:
        raise PackValidationError("MEMORY_PACK_INTEGRITY_MISMATCH", "Memory Pack 完整性校验失败。")
    canonical_json = rfc8785.dumps(pack).decode("utf-8")
    return pack, canonical_json, hashlib.sha256(raw).hexdigest()


def analyze_pack(raw: bytes, existing_cards: list[dict[str, Any]]) -> PackPreviewAnalysis:
    pack, canonical_json, file_hash = parse_pack_bytes(raw)
    explicit_conflicts = _validate_relations(pack)
    existing_hashes = {_card_fingerprint(card) for card in existing_cards}
    items: list[dict[str, Any]] = []
    for card in pack["cards"]:
        classification = "legal_new"
        reason: str | None = None
        if _contains_suspicious_text(card):
            classification, reason = "suspicious", "suspicious_text"
        elif _card_fingerprint(card) in existing_hashes:
            classification, reason = "duplicate", "exact_duplicate"
        elif card["external_id"] in explicit_conflicts:
            classification, reason = "potential_conflict", "declared_conflict"
        else:
            overlapping = [
                existing
                for existing in existing_cards
                if _scope_overlap(card["scope"], existing.get("scope") or {})
            ]
            documents = [_card_document(card), *(_card_document(item) for item in overlapping)]
            vectors = compute_tfidf_vectors(documents)
            if any(cosine_similarity(vectors[0], vector) >= 0.68 for vector in vectors[1:]):
                classification, reason = "potential_conflict", "scope_overlap_similarity"
        items.append(
            {
                "external_id": card["external_id"],
                "kind": card["kind"],
                "title": card["title"],
                "rule": card["rule"],
                "avoid": card["avoid"],
                "scope": card["scope"],
                "classification": classification,
                "reason": reason,
            }
        )
    return PackPreviewAnalysis(pack, canonical_json, file_hash, items)
