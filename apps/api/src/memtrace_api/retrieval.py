"""Deterministic, owner-scoped Day 4 character TF-IDF retrieval primitives."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from memtrace_api.schemas import CurrentConstraints, RetrievalReasonCode, TaskFingerprint

RETRIEVAL_MODE = "tfidf"
ALGORITHM_VERSION = "char_tfidf_v1"
THRESHOLD = 0.68
TOP_K = 3
SCOPE_WEIGHTS = {
    "domain": 0.25,
    "task_type": 0.25,
    "artifact_type": 0.10,
    "audience": 0.10,
    "project_key": 0.10,
    "language": 0.05,
    "framework": 0.05,
    "concepts": 0.10,
}


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def generate_ngrams(text: str) -> list[str]:
    if len(text) < 2:
        return []
    return [
        text[index : index + size]
        for size in range(2, min(4, len(text)) + 1)
        for index in range(len(text) - size + 1)
    ]


def build_vector(ngrams: list[str]) -> dict[str, float]:
    counts = Counter(ngrams)
    total = sum(counts.values())
    return {} if total == 0 else {term: count / total for term, count in counts.items()}


def compute_tfidf_vectors(documents: list[str]) -> list[dict[str, float]]:
    normalized = [normalize_text(document) for document in documents]
    term_frequencies = [build_vector(generate_ngrams(document)) for document in normalized]
    terms = set().union(*(set(vector) for vector in term_frequencies))
    document_count = len(documents)
    inverse_document_frequency = {
        term: math.log(
            (1 + document_count) / (1 + sum(1 for vector in term_frequencies if term in vector))
        )
        + 1
        for term in terms
    }
    vectors: list[dict[str, float]] = []
    for frequencies in term_frequencies:
        weighted = {
            term: frequencies[term] * inverse_document_frequency[term] for term in frequencies
        }
        norm = math.sqrt(sum(value * value for value in weighted.values()))
        vectors.append(
            {} if norm == 0 else {term: value / norm for term, value in weighted.items()}
        )
    return vectors


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    value = sum(weight * right.get(term, 0.0) for term, weight in left.items())
    return max(0.0, min(1.0, value))


def safe_round(value: float, digits: int = 6) -> float:
    return round(value, digits)


def longest_common_substring_len(left: str, right: str, limit: int) -> int:
    """Return the longest contiguous match, bounded for deterministic verifier use."""
    normalized_left = normalize_text(left)[:limit]
    normalized_right = normalize_text(right)
    if not normalized_left or not normalized_right:
        return 0
    previous = [0] * (len(normalized_right) + 1)
    longest = 0
    for left_character in normalized_left:
        current = [0]
        for index, right_character in enumerate(normalized_right, start=1):
            length = previous[index - 1] + 1 if left_character == right_character else 0
            current.append(length)
            longest = max(longest, length)
        previous = current
    return longest


def compute_verified_effect(helpful: int, harmful: int, stale: int) -> float:
    return (helpful + 1) / (helpful + harmful + stale + 2)


def compute_recency(source_type: str, created_at: datetime | None) -> float:
    if source_type in {
        "explicit_feedback",
        "explicit_correction",
        "edit_diff",
        "accept",
        "rating",
    }:
        return 1.0
    if source_type not in {"outcome", "import"} or created_at is None:
        return 0.0
    aware = created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
    age_days = max(0.0, (datetime.now(UTC) - aware).total_seconds() / 86_400)
    return max(0.0, 1.0 - age_days / 90.0)


def _value(value: object) -> str | None:
    if value is None:
        return None
    raw = value.value if hasattr(value, "value") else value
    normalized = str(raw).strip().casefold()
    return normalized or None


def compute_scope_match(scope: dict[str, Any], fingerprint: TaskFingerprint) -> float:
    score = 0.0
    for field_name in (
        "domain",
        "task_type",
        "artifact_type",
        "audience",
        "project_key",
        "language",
        "framework",
    ):
        memory_value = _value(scope.get(field_name))
        task_value = _value(getattr(fingerprint, field_name))
        weight = SCOPE_WEIGHTS[field_name]
        if memory_value == "any":
            score += weight / 2
        elif memory_value is not None and task_value is not None and memory_value == task_value:
            score += weight

    memory_concepts = {normalize_text(item) for item in scope.get("concepts", []) if item}
    task_concepts = {normalize_text(item) for item in fingerprint.concepts if item}
    if memory_concepts and task_concepts:
        score += (
            len(memory_concepts & task_concepts)
            / len(memory_concepts | task_concepts)
            * SCOPE_WEIGHTS["concepts"]
        )
    return score


def _json(value: str | list[Any] | dict[str, Any] | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def check_hard_filters(
    card: Any,
    fingerprint: TaskFingerprint,
    effective_memory_mode: str,
    constraints: CurrentConstraints,
    *,
    active_conflict_ids: set[str] | None = None,
) -> tuple[bool, list[RetrievalReasonCode]]:
    if effective_memory_mode == "off" or constraints.memory_disabled:
        return False, [RetrievalReasonCode.MEMORY_MODE_OFF]
    if card.status != "active":
        return False, [RetrievalReasonCode.STATUS_NOT_ACTIVE]
    if (
        card.current_version_id is None
        or card.version < 1
        or card.rule_confidence is None
        or card.scope_confidence is None
    ):
        return False, [RetrievalReasonCode.INVALID_ACTIVE_CARD]

    now = datetime.now(UTC)
    valid_from = card.valid_from
    valid_to = card.valid_to
    if valid_from is not None:
        valid_from = valid_from.replace(tzinfo=UTC) if valid_from.tzinfo is None else valid_from
        if valid_from > now:
            return False, [RetrievalReasonCode.NOT_YET_VALID]
    if valid_to is not None:
        valid_to = valid_to.replace(tzinfo=UTC) if valid_to.tzinfo is None else valid_to
        if valid_to <= now:
            return False, [RetrievalReasonCode.EXPIRED]

    scope = _json(card.scope_json, {})
    field_reasons = {
        "domain": RetrievalReasonCode.SCOPE_DOMAIN_MISMATCH,
        "task_type": RetrievalReasonCode.SCOPE_TASK_TYPE_MISMATCH,
        "artifact_type": RetrievalReasonCode.SCOPE_ARTIFACT_MISMATCH,
        "audience": RetrievalReasonCode.SCOPE_AUDIENCE_MISMATCH,
        "project_key": RetrievalReasonCode.SCOPE_PROJECT_MISMATCH,
        "language": RetrievalReasonCode.SCOPE_LANGUAGE_MISMATCH,
        "framework": RetrievalReasonCode.SCOPE_FRAMEWORK_MISMATCH,
    }
    for field_name, reason in field_reasons.items():
        memory_value = _value(scope.get(field_name))
        task_value = _value(getattr(fingerprint, field_name))
        if memory_value not in {None, "any"} and task_value != memory_value:
            return False, [reason]

    exceptions = set(_json(card.exceptions_json, []))
    if (
        constraints.response_policy.value == "direct_fix"
        and "response_policy:direct_fix" in exceptions
    ) or (constraints.urgency.value == "urgent" and "urgency:urgent" in exceptions):
        return False, [RetrievalReasonCode.CURRENT_CONSTRAINT_OVERRIDE]
    if active_conflict_ids and card.id in active_conflict_ids:
        return False, [RetrievalReasonCode.ACTIVE_CONFLICT]
    return True, []


def build_memory_document(card: Any) -> str:
    scope = _json(card.scope_json, {})
    structured_scope = " ".join(
        part
        for part in (
            f"domain:{scope.get('domain')}" if scope.get("domain") else "",
            f"task_type:{scope.get('task_type')}" if scope.get("task_type") else "",
            f"language:{scope.get('language')}" if scope.get("language") else "",
            *(f"concept:{concept}" for concept in scope.get("concepts", [])),
        )
        if part
    )
    return "\n".join(
        (
            card.title,
            card.rule,
            card.trigger_text or "",
            structured_scope,
        )
    )


def current_version_created_at(card: Any) -> datetime | None:
    for version in getattr(card, "versions", ()):
        if version.id == card.current_version_id:
            return version.created_at
    return card.created_at


@dataclass(slots=True)
class RetrievalDecision:
    memory_id: str
    memory_version_id: str | None
    memory_status: str
    retrieved: bool
    selected: bool = False
    injected: bool = False
    rank: int | None = None
    scope_match: float | None = None
    semantic_similarity: float | None = None
    provenance_confidence: float | None = None
    verified_effect: float | None = None
    recency: float | None = None
    final_score: float | None = None
    estimated_tokens: int = 0
    reason_codes: list[RetrievalReasonCode] = field(default_factory=list)


@dataclass(slots=True)
class RetrievalResult:
    trace_id: str
    request_id: str
    task_id: str
    run_id: str
    candidate_count: int = 0
    retrieval_ms: int = 0
    decisions: list[RetrievalDecision] = field(default_factory=list)
    memory_context: str | None = None
    memory_tokens_estimated: int = 0
    prompt_section_hash: str | None = None
    reason_codes: list[RetrievalReasonCode] = field(default_factory=list)
