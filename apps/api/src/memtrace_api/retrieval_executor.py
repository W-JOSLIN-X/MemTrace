"""Execute G3 retrieval, scoring, and deterministic prompt budgeting."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any

from memtrace_api.retrieval import (
    ALGORITHM_VERSION,
    RETRIEVAL_MODE,
    THRESHOLD,
    TOP_K,
    RetrievalDecision,
    RetrievalResult,
    build_memory_document,
    check_hard_filters,
    compute_recency,
    compute_scope_match,
    compute_tfidf_vectors,
    compute_verified_effect,
    cosine_similarity,
    current_version_created_at,
    safe_round,
)
from memtrace_api.schemas import (
    CurrentConstraints,
    RetrievalDecisionResponse,
    RetrievalReasonCode,
    RetrievalTraceResponse,
    TaskFingerprint,
    utc_now,
)

CONTEXT_OPEN = '<MEMORY_CONTEXT permission="advisory" data_only="true">'
CONTEXT_CLOSE = "</MEMORY_CONTEXT>"


def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def estimate_tokens(text: str) -> int:
    return 0 if not text else math.ceil(len(text.encode("utf-8")) / 3)


def compile_memory_block(
    memory_id: str,
    version_id: str,
    score: float,
    when: str,
    rule: str,
    avoid: str,
    exceptions: str,
) -> str:
    return (
        f'<MEMORY id="{memory_id}" version="{version_id}" score="{score:.6f}">\n'
        f"<WHEN>{escape_xml(when)}</WHEN>\n"
        f"<DO>{escape_xml(rule)}</DO>\n"
        f"<AVOID>{escape_xml(avoid)}</AVOID>\n"
        f"<EXCEPT>{escape_xml(exceptions)}</EXCEPT>\n"
        "</MEMORY>"
    )


def compile_prompt_section(blocks: list[str]) -> tuple[str, int, str]:
    if not blocks:
        return "", 0, ""
    section = f"{CONTEXT_OPEN}\n" + "\n".join(blocks) + f"\n{CONTEXT_CLOSE}"
    return (
        section,
        estimate_tokens(section),
        hashlib.sha256(section.encode("utf-8")).hexdigest(),
    )


def _truncate(value: str) -> str:
    if not value:
        return value
    return "…" if len(value) <= 2 else value[:-2] + "…"


def compile_budgeted_block(card: Any, score: float) -> tuple[str, int] | None:
    scope = json.loads(card.scope_json) if isinstance(card.scope_json, str) else card.scope_json
    exceptions = (
        json.loads(card.exceptions_json)
        if isinstance(card.exceptions_json, str)
        else card.exceptions_json
    )
    values = {
        "when": card.trigger_text or _scope_summary(scope),
        "rule": card.rule,
        "avoid": card.avoid,
        "exceptions": ",".join(exceptions or []),
    }

    def render() -> str:
        return compile_memory_block(
            card.id,
            card.current_version_id,
            score,
            values["when"],
            values["rule"],
            values["avoid"],
            values["exceptions"],
        )

    block = render()
    for field_name in ("exceptions", "avoid", "when", "rule"):
        while estimate_tokens(block) > 100 and len(values[field_name]) > 1:
            values[field_name] = _truncate(values[field_name])
            block = render()
    return None if estimate_tokens(block) > 100 else (block, estimate_tokens(block))


def _scope_summary(scope: dict[str, Any]) -> str:
    fields = (
        "domain",
        "task_type",
        "artifact_type",
        "audience",
        "project_key",
        "language",
        "framework",
    )
    values = [str(scope[field]) for field in fields if scope.get(field)]
    return ",".join(values) or "unknown"


@dataclass(frozen=True, slots=True)
class RetrievalContext:
    task_id: str
    run_id: str
    request_id: str
    fingerprint: TaskFingerprint
    effective_memory_mode: str
    current_constraints: CurrentConstraints
    active_conflict_ids: frozenset[str] = frozenset()


def execute_retrieval(
    cards: list[Any],
    context: RetrievalContext,
    trace_id: str,
) -> RetrievalResult:
    started = time.perf_counter()
    result = RetrievalResult(
        trace_id=trace_id,
        request_id=context.request_id,
        task_id=context.task_id,
        run_id=context.run_id,
        candidate_count=len(cards),
    )
    if context.effective_memory_mode == "off" or context.current_constraints.memory_disabled:
        result.candidate_count = 0
        result.reason_codes = [RetrievalReasonCode.MEMORY_MODE_OFF]
        result.retrieval_ms = max(0, round((time.perf_counter() - started) * 1000))
        return result

    passed: list[Any] = []
    for card in cards:
        accepted, reasons = check_hard_filters(
            card,
            context.fingerprint,
            context.effective_memory_mode,
            context.current_constraints,
            active_conflict_ids=set(context.active_conflict_ids),
        )
        if accepted:
            passed.append(card)
        else:
            result.decisions.append(
                RetrievalDecision(
                    memory_id=card.id,
                    memory_version_id=card.current_version_id,
                    memory_status=card.status,
                    retrieved=False,
                    reason_codes=reasons,
                )
            )

    if passed:
        documents = [context.fingerprint.semantic_query] + [
            build_memory_document(card) for card in passed
        ]
        vectors = compute_tfidf_vectors(documents)
        query_vector = vectors[0]
        for card, memory_vector in zip(passed, vectors[1:], strict=True):
            if not query_vector or not memory_vector:
                result.decisions.append(
                    RetrievalDecision(
                        memory_id=card.id,
                        memory_version_id=card.current_version_id,
                        memory_status=card.status,
                        retrieved=True,
                        semantic_similarity=0.0,
                        reason_codes=[RetrievalReasonCode.EMPTY_VECTOR],
                    )
                )
                continue
            scope = json.loads(card.scope_json)
            semantic = cosine_similarity(query_vector, memory_vector)
            scope_score = compute_scope_match(scope, context.fingerprint)
            provenance = min(card.source_trust, card.rule_confidence, card.scope_confidence)
            verified = compute_verified_effect(
                card.helpful_count,
                card.harmful_count,
                card.stale_count,
            )
            recency = compute_recency(card.source_type, current_version_created_at(card))
            final = (
                0.25 * scope_score
                + 0.30 * semantic
                + 0.15 * provenance
                + 0.15 * verified
                + 0.15 * recency
            )
            result.decisions.append(
                RetrievalDecision(
                    memory_id=card.id,
                    memory_version_id=card.current_version_id,
                    memory_status=card.status,
                    retrieved=True,
                    scope_match=scope_score,
                    semantic_similarity=semantic,
                    provenance_confidence=provenance,
                    verified_effect=verified,
                    recency=recency,
                    final_score=final,
                )
            )

    eligible = sorted(
        (
            decision
            for decision in result.decisions
            if decision.retrieved
            and decision.final_score is not None
            and decision.final_score >= THRESHOLD
        ),
        key=lambda decision: (
            -float(decision.final_score),
            -float(decision.semantic_similarity or 0),
            decision.memory_id,
        ),
    )
    selected_ids = {decision.memory_id for decision in eligible[:TOP_K]}
    ranks = {decision.memory_id: rank for rank, decision in enumerate(eligible[:TOP_K], 1)}
    for decision in result.decisions:
        if decision.memory_id in selected_ids:
            decision.selected = True
            decision.rank = ranks[decision.memory_id]
            decision.reason_codes = [RetrievalReasonCode.SELECTED_ABOVE_THRESHOLD]
        elif decision in eligible:
            decision.reason_codes = [RetrievalReasonCode.TOP_K_EXCEEDED]
        elif decision.retrieved and not decision.reason_codes:
            decision.reason_codes = [RetrievalReasonCode.BELOW_THRESHOLD]

    cards_by_id = {card.id: card for card in passed}
    blocks: list[str] = []
    for decision in sorted(
        (item for item in result.decisions if item.selected),
        key=lambda item: item.rank or TOP_K + 1,
    ):
        compiled = compile_budgeted_block(
            cards_by_id[decision.memory_id], decision.final_score or 0
        )
        if compiled is None:
            decision.reason_codes.append(RetrievalReasonCode.PROMPT_BUDGET_EXCEEDED)
            continue
        block, block_tokens = compiled
        candidate_blocks = [*blocks, block]
        section, total_tokens, section_hash = compile_prompt_section(candidate_blocks)
        if total_tokens > 300:
            decision.reason_codes.append(RetrievalReasonCode.PROMPT_BUDGET_EXCEEDED)
            continue
        blocks = candidate_blocks
        decision.injected = True
        decision.estimated_tokens = block_tokens
        result.memory_context = section
        result.memory_tokens_estimated = total_tokens
        result.prompt_section_hash = section_hash

    result.retrieval_ms = max(0, round((time.perf_counter() - started) * 1000))
    return result


def to_response(result: RetrievalResult) -> RetrievalTraceResponse:
    now = utc_now()
    return RetrievalTraceResponse(
        request_id=result.request_id,
        retrieval_trace_id=result.trace_id,
        task_id=result.task_id,
        run_id=result.run_id,
        retrieval_mode=RETRIEVAL_MODE,
        algorithm_version=ALGORITHM_VERSION,
        threshold=THRESHOLD,
        top_k=TOP_K,
        candidate_count=result.candidate_count,
        retrieved_count=sum(decision.retrieved for decision in result.decisions),
        selected_count=sum(decision.selected for decision in result.decisions),
        injected_count=sum(decision.injected for decision in result.decisions),
        decisions=[
            RetrievalDecisionResponse(
                memory_id=decision.memory_id,
                memory_version_id=decision.memory_version_id,
                memory_status=decision.memory_status,
                retrieved=decision.retrieved,
                selected=decision.selected,
                injected=decision.injected,
                rank=decision.rank,
                scope_match=_rounded(decision.scope_match),
                semantic_similarity=_rounded(decision.semantic_similarity),
                provenance_confidence=_rounded(decision.provenance_confidence),
                verified_effect=_rounded(decision.verified_effect),
                recency=_rounded(decision.recency),
                final_score=_rounded(decision.final_score),
                reason_codes=decision.reason_codes,
            )
            for decision in result.decisions
        ],
        retrieval_ms=result.retrieval_ms,
        memory_chars=len(result.memory_context or ""),
        memory_tokens_estimated=result.memory_tokens_estimated,
        provider_prompt_tokens_actual=None,
        prompt_section_hash=result.prompt_section_hash,
        reason_codes=result.reason_codes,
        created_at=now,
        updated_at=now,
    )


def _rounded(value: float | None) -> float | None:
    return None if value is None else safe_round(value)
