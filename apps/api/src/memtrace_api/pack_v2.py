"""Strict, data-only Memory Pack v2 parsing and preview classification."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import rfc8785
from pydantic import ValidationError

from memtrace_api.pack_service import PackValidationError
from memtrace_api.schemas import MemoryPackV2Document

MAX_PACK_SIZE = 1_048_576
MAX_DEPTH = 12
MAX_SCALAR_NODES = 10_000
MAX_STRING = 10_000

_FORBIDDEN_KEYS = {
    "allowed_tools",
    "api_key",
    "command",
    "executable",
    "role",
    "script",
    "secret",
    "system_prompt",
    "token",
    "tool",
    "tools",
    "url_fetch",
}
_SUSPICIOUS_TEXT = re.compile(
    r"(?i)(<\s*script\b|javascript\s*:|data\s*:\s*text/html|"
    r"on(?:error|load)\s*=|ignore\s+(?:all\s+)?previous\s+instructions|"
    r"system\s+prompt|BEGIN\s+(?:RSA|OPENSSH)\s+PRIVATE\s+KEY)"
)


@dataclass(frozen=True, slots=True)
class PackV2Analysis:
    document: MemoryPackV2Document
    canonical_json: str
    file_hash: str
    items: list[dict[str, Any]]

    @property
    def counts(self) -> dict[str, int]:
        return {
            classification: sum(item["classification"] == classification for item in self.items)
            for classification in (
                "legal_new",
                "duplicate",
                "potential_conflict",
                "suspicious",
            )
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
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in _FORBIDDEN_KEYS:
                raise PackValidationError("MEMORY_PACK_INVALID", "Pack 包含禁止字段。")
            _inspect_tree(child, depth=depth + 1, counter=counter)
        return
    if isinstance(value, list):
        for child in value:
            _inspect_tree(child, depth=depth + 1, counter=counter)
        return
    counter[0] += 1
    if counter[0] > MAX_SCALAR_NODES:
        raise PackValidationError("MEMORY_PACK_INVALID", "Pack scalar 节点数量超过限制。")
    if isinstance(value, str) and len(value) > MAX_STRING:
        raise PackValidationError("MEMORY_PACK_INVALID", "Pack 字符串长度超过限制。")


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _fingerprint(kind: str, content: str, applies_when: str) -> str:
    return hashlib.sha256(
        rfc8785.dumps(
            {
                "kind": kind,
                "content": _normalized(content),
                "applies_when": _normalized(applies_when),
            }
        )
    ).hexdigest()


def parse_pack_v2_bytes(raw: bytes) -> tuple[MemoryPackV2Document, str, str]:
    if len(raw) > MAX_PACK_SIZE:
        raise PackValidationError(
            "MEMORY_PACK_TOO_LARGE", "Memory Pack 超过 1 MiB 限制。", status_code=413
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackValidationError("MEMORY_PACK_INVALID", "Memory Pack 必须使用 UTF-8。") from exc
    try:
        unpacked = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except PackValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PackValidationError("MEMORY_PACK_INVALID", "Memory Pack 不是有效 JSON。") from exc
    if not isinstance(unpacked, dict):
        raise PackValidationError("MEMORY_PACK_INVALID", "Memory Pack 根节点必须是对象。")
    _inspect_tree(unpacked)
    try:
        document = MemoryPackV2Document.model_validate(unpacked)
    except ValidationError as exc:
        raise PackValidationError("MEMORY_PACK_INVALID", "Memory Pack 不符合 v2 Schema。") from exc
    payload = {key: value for key, value in unpacked.items() if key != "integrity"}
    actual_hash = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    if document.integrity.canonical_payload_sha256 != actual_hash:
        raise PackValidationError("MEMORY_PACK_INTEGRITY_MISMATCH", "Memory Pack 完整性校验失败。")
    canonical_json = rfc8785.dumps(unpacked).decode("utf-8")
    return document, canonical_json, hashlib.sha256(raw).hexdigest()


def analyze_pack_v2(raw: bytes, existing_cards: list[dict[str, str]]) -> PackV2Analysis:
    document, canonical_json, file_hash = parse_pack_v2_bytes(raw)
    existing_fingerprints = {
        _fingerprint(card["kind"], card["content"], card["applies_when"]) for card in existing_cards
    }
    declared_conflicts = {
        external_id
        for relation in document.relations
        if relation.relation_type == "conflicts_with"
        for external_id in (relation.from_external_id, relation.to_external_id)
    }
    items: list[dict[str, Any]] = []
    for card in document.cards:
        classification = "legal_new"
        reason: str | None = None
        if _SUSPICIOUS_TEXT.search(card.content) or _SUSPICIOUS_TEXT.search(card.applies_when):
            classification, reason = "suspicious", "suspicious_text"
        elif (
            _fingerprint(card.kind.value, card.content, card.applies_when) in existing_fingerprints
        ):
            classification, reason = "duplicate", "exact_duplicate"
        elif card.external_id in declared_conflicts:
            classification, reason = "potential_conflict", "declared_conflict"
        items.append(
            {
                "external_id": card.external_id,
                "kind": card.kind.value,
                "content": card.content,
                "applies_when": card.applies_when,
                "classification": classification,
                "reason": reason,
            }
        )
    return PackV2Analysis(document, canonical_json, file_hash, items)
