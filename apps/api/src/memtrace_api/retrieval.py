"""Deterministic character n-gram TF-IDF retriever for G3."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from memtrace_api.schemas import (
    CurrentConstraints,
    MemoryScope,
    RetrievalDecisionResponse,
    RetrievalReasonCode,
    RetrievalTraceResponse,
    TaskFingerprint,
    utc_now,
)

# G3 frozen constants
RETRIEVAL_MODE = "tfidf"
ALGORITHM_VERSION = "char_tfidf_v1"
THRESHOLD = 0.68
TOP_K = 3

NGRAM_MIN = 2
NGRAM_MAX = 4

SCOPE_WEIGHTS = {
    "domain": 0.25,
    "task_type": 0.25,
    "artifact": 0.10,
    "audience": 0.10,
    "project": 0.10,
    "language": 0.05,
    "framework": 0.05,
    "concepts": 0.10,
}

SCOPE_ANY_KEYWORDS = {"any"}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def generate_ngrams(text: str) -> list[str]:
    if len(text) < NGRAM_MIN:
        return []
    grams = []
    for n in range(NGRAM_MIN, min(NGRAM_MAX, len(text)) + 1):
        for i in range(len(text) - n + 1):
            grams.append(text[i:i + n])
    return grams


def build_vector(ngrams: list[str]) -> dict[str, float]:
    counter = Counter(ngrams)
    total = sum(counter.values())
    if total == 0:
        return {}
    return {g: c / total for g, c in counter.items()}


def compute_tfidf_vectors(docs: list[str]):
    n = len(docs)
    raw_vectors = []
    all_terms = set()
    for doc in docs:
        vec = build_vector(generate_ngrams(doc))
        raw_vectors.append(vec)
        all_terms.update(vec.keys())

    idf = {}
    for term in all_terms:
        df = sum(1 for v in raw_vectors if term in v)
        idf[term] = math.log((1 + n) / (1 + df)) + 1

    tfidf = []
    for raw in raw_vectors:
        weighted = {t: raw.get(t, 0) * idf.get(t, 1) for t in all_terms}
        norm = math.sqrt(sum(v ** 2 for v in weighted.values()))
        if norm == 0:
            tfidf.append({})
        else:
            tfidf.append({t: v / norm for t, v in weighted.items()})
    return tfidf


def cosine_similarity(a, b) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in a)
    return max(0.0, min(1.0, dot))


def safe_round(value: float, digits=6) -> float:
    return round(value, digits)


def longest_common_substring_len(s1: str, s2: str, max_len: int) -> int:
    if not s1 or not s2:
        return 0
    m, n = len(s1), len(s2)
    dp = [0] * (n + 1)
    best = 0
    for i in range(1, m + 1):
        ndp = [0] * (n + 1)
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                ndp[j] = dp[j - 1] + 1
                if ndp[j] > best:
                    best = ndp[j]
                    if best >= max_len:
                        return best
        dp = ndp
    return best


def compute_verified_effect(helpful: int, harmful: int, stale: int) -> float:
    return (helpful + 1) / (helpful + harmful + stale + 2)


def compute_recency(source_type: str, created_at: Optional[datetime]) -> float:
    explicit = {"explicit_feedback", "explicit_correction", "edit_diff", "accept", "rating"}
    if source_type in explicit:
        return 1.0
    if source_type in {"outcome", "import"}:
        if created_at is None:
            return 0.0
        age = (datetime.now(UTC) - created_at).total_seconds() / 86400.0
        return max(0.0, 1.0 - age / 90.0)
    return 0.0


def compute_scope_match(card_scope: dict, fp: TaskFingerprint) -> float:
    score = 0.0

    def mf(card_val, fp_val, w):
        if card_val is None or str(card_val) in ("", "null"):
            return 0.0
        cs = str(card_val).lower().strip()
        if cs in SCOPE_ANY_KEYWORDS:
            return w * 0.5
        if fp_val is None:
            return 0.0
        fs = str(fp_val.value if hasattr(fp_val, "value") else fp_val).lower().strip()
        return w if cs == fs else 0.0

    score += mf(card_scope.get("domain"), fp.domain, SCOPE_WEIGHTS["domain"])
    score += mf(card_scope.get("task_type"), fp.task_type, SCOPE_WEIGHTS["task_type"])
    score += mf(card_scope.get("artifact_type"), fp.artifact_type, SCOPE_WEIGHTS["artifact"])
    score += mf(card_scope.get("audience"), fp.audience, SCOPE_WEIGHTS["audience"])
    score += mf(card_scope.get("project_key"), fp.project_key, SCOPE_WEIGHTS["project"])
    score += mf(card_scope.get("language"), fp.language, SCOPE_WEIGHTS["language"])
    score += mf(card_scope.get("framework"), None, SCOPE_WEIGHTS["framework"])

    card_c = set(card_scope.get("concepts") or [])
    fp_c = set(c for c in fp.concepts if c)
    if card_c and fp_c:
        score += (len(card_c & fp_c) / len(card_c | fp_c)) * SCOPE_WEIGHTS["concepts"]
    return score


def check_hard_filters(card, fingerprint: TaskFingerprint, eff_mode: str, cc: CurrentConstraints):
    if eff_mode == "off" or cc.memory_disabled:
        return False, [RetrievalReasonCode.MEMORY_MODE_OFF]
    if card.status != "active":
        return False, [RetrievalReasonCode.STATUS_NOT_ACTIVE]
    if card.current_version_id is None or card.version < 1:
        return False, [RetrievalReasonCode.INVALID_ACTIVE_CARD]
    if card.rule_confidence is None or card.scope_confidence is None:
        return False, [RetrievalReasonCode.INVALID_ACTIVE_CARD]

    now = datetime.now(UTC)
    if card.valid_from is not None and card.valid_from > now:
        return False, [RetrievalReasonCode.NOT_YET_VALID]
    if card.valid_to is not None and card.valid_to <= now:
        return False, [RetrievalReasonCode.EXPIRED]

    cs = json.loads(card.scope_json) if isinstance(card.scope_json, str) else card.scope_json
    exc = json.loads(card.exceptions_json) if isinstance(card.exceptions_json, str) else (card.exceptions_json or [])

    d = cs.get("domain")
    if d is not None and str(d).lower() not in ("", "null", "any") and str(d) != fingerprint.domain.value:
        return False, [RetrievalReasonCode.SCOPE_DOMAIN_MISMATCH]
    tt = cs.get("task_type")
    if tt is not None and str(tt).lower() not in ("", "null") and str(tt) != fingerprint.task_type.value:
        return False, [RetrievalReasonCode.SCOPE_TASK_TYPE_MISMATCH]
    art = cs.get("artifact_type")
    if art is not None and str(art).lower() not in ("", "null") and str(art) != fingerprint.artifact_type.value:
        return False, [RetrievalReasonCode.SCOPE_ARTIFACT_MISMATCH]
    aud = cs.get("audience")
    if aud is not None and str(aud).lower() not in ("", "null") and str(aud) != fingerprint.audience.value:
        return False, [RetrievalReasonCode.SCOPE_AUDIENCE_MISMATCH]
    pk = cs.get("project_key")
    fp_pk = fingerprint.project_key
    if pk is not None and str(pk).strip() and (fp_pk is None or not str(fp_pk).strip() or str(pk) != str(fp_pk)):
        return False, [RetrievalReasonCode.SCOPE_PROJECT_MISMATCH]

    if cc.response_policy.value == "direct_fix" and "response_policy:direct_fix" in exc:
        return False, [RetrievalReasonCode.CURRENT_CONSTRAINT_OVERRIDE]
    if cc.urgency.value == "urgent" and "urgency:urgent" in exc:
        return False, [RetrievalReasonCode.CURRENT_CONSTRAINT_OVERRIDE]

    return True, []


def build_memory_document(card) -> str:
    cs = json.loads(card.scope_json) if isinstance(card.scope_json, str) else card.scope_json
    concepts = cs.get("concepts") or []
    return "\n".join([str(card.title), str(card.rule), str(card.trigger_text or ""), " ".join(str(c) for c in concepts)])


@dataclass
class RetrievalDecision:
    memory_id: str
    memory_version_id: Optional[str]
    memory_status: str
    retrieved: bool
    selected: bool
    injected: bool
    rank: Optional[int]
    scope_match: Optional[float]
    semantic_similarity: Optional[float]
    provenance_confidence: Optional[float]
    verified_effect: Optional[float]
    recency: Optional[float]
    final_score: Optional[float]
    reason_codes: list = field(default_factory=list)


@dataclass
class RetrievalResult:
    trace_id: str
    request_id: str
    task_id: str
    run_id: str
    retrieval_ms: int
    decisions: list = field(default_factory=list)
    memory_context: Optional[str] = None
    memory_tokens_estimated: int = 0
    prompt_section_hash: Optional[str] = None
    reason_codes: list = field(default_factory=list)


def to_response(result, trace_id, task_id, run_id, retrieval_ms) -> RetrievalTraceResponse:
    decisions = [
        RetrievalDecisionResponse(
            memory_id=d.memory_id,
            memory_version_id=d.memory_version_id,
            memory_status=d.memory_status,
            retrieved=d.retrieved,
            selected=d.selected,
            injected=d.injected,
            rank=d.rank,
            scope_match=safe_round(d.scope_match) if d.scope_match is not None else None,
            semantic_similarity=safe_round(d.semantic_similarity) if d.semantic_similarity is not None else None,
            provenance_confidence=safe_round(d.provenance_confidence) if d.provenance_confidence is not None else None,
            verified_effect=safe_round(d.verified_effect) if d.verified_effect is not None else None,
            recency=safe_round(d.recency) if d.recency is not None else None,
            final_score=safe_round(d.final_score) if d.final_score is not None else None,
            reason_codes=d.reason_codes,
        )
        for d in result.decisions
    ]
    return RetrievalTraceResponse(
        request_id=result.request_id,
        retrieval_trace_id=result.trace_id,
        task_id=task_id,
        run_id=run_id,
        retrieval_mode=RETRIEVAL_MODE,
        algorithm_version=ALGORITHM_VERSION,
        threshold=THRESHOLD,
        top_k=TOP_K,
        candidate_count=sum(1 for d in result.decisions if d.retrieved),
        retrieved_count=sum(1 for d in result.decisions if d.retrieved),
        selected_count=sum(1 for d in result.decisions if d.selected),
        injected_count=sum(1 for d in result.decisions if d.injected),
        decisions=decisions,
        retrieval_ms=retrieval_ms,
        memory_chars=len(result.memory_context) if result.memory_context else 0,
        memory_tokens_estimated=result.memory_tokens_estimated,
        provider_prompt_tokens_actual=None,
        prompt_section_hash=result.prompt_section_hash,
        reason_codes=result.reason_codes,
        created_at=utc_now(),
    )
