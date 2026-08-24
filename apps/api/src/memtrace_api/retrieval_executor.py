"""G3 retrieval executor: hard filters -> TF-IDF scoring -> selection -> prompt compilation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from memtrace_api.retrieval import (
    ALGORITHM_VERSION,
    RETRIEVAL_MODE,
    THRESHOLD,
    TOP_K,
    RetrievalDecision,
    RetrievalResult,
    RetrievalReasonCode,
    build_memory_document,
    check_hard_filters,
    compute_recency,
    compute_scope_match,
    compute_tfidf_vectors,
    compute_verified_effect,
    cosine_similarity,
    safe_round,
    generate_ngrams,
    build_vector,
)


def escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text.encode("utf-8")) / 3)


def compile_memory_block(
    mem_id: str, ver_id: str, score: float, when: str, do: str, avoid: str, exc: str
) -> str:
    return (
        f'<MEMORY id="{mem_id}" version="{ver_id}" score="{safe_round(score):.6f}">\n'
        f"<WHEN>{escape_xml(when)}</WHEN>\n"
        f"<DO>{escape_xml(do)}</DO>\n"
        f"<AVOID>{escape_xml(avoid)}</AVOID>\n"
        f"<EXCEPT>{escape_xml(exc)}</EXCEPT>\n"
        f"</MEMORY>"
    )


def compile_prompt_section(block_texts: list[str]) -> tuple[str, int, str]:
    section = (
        '<MEMORY_CONTEXT permission="advisory" data_only="true">\n'
        + "\n".join(block_texts)
        + "\n</MEMORY_CONTEXT>"
    )
    tokens = estimate_tokens(section)
    h = hashlib.sha256(section.encode("utf-8")).hexdigest()
    return section, tokens, h


def _scope_summary(cs: dict) -> str:
    parts = []
    if cs.get("domain"):
        parts.append(str(cs["domain"]))
    if cs.get("task_type"):
        parts.append(str(cs["task_type"]))
    return ", ".join(parts) or "general context"


def _reason_code_str(name: str) -> RetrievalReasonCode:
    mapping = {
        "memory_mode_off": RetrievalReasonCode.MEMORY_MODE_OFF,
        "status_not_active": RetrievalReasonCode.STATUS_NOT_ACTIVE,
        "not_yet_valid": RetrievalReasonCode.NOT_YET_VALID,
        "expired": RetrievalReasonCode.EXPIRED,
        "scope_domain_mismatch": RetrievalReasonCode.SCOPE_DOMAIN_MISMATCH,
        "scope_task_type_mismatch": RetrievalReasonCode.SCOPE_TASK_TYPE_MISMATCH,
        "scope_artifact_mismatch": RetrievalReasonCode.SCOPE_ARTIFACT_MISMATCH,
        "scope_audience_mismatch": RetrievalReasonCode.SCOPE_AUDIENCE_MISMATCH,
        "scope_project_mismatch": RetrievalReasonCode.SCOPE_PROJECT_MISMATCH,
        "current_constraint_override": RetrievalReasonCode.CURRENT_CONSTRAINT_OVERRIDE,
        "invalid_active_card": RetrievalReasonCode.INVALID_ACTIVE_CARD,
        "empty_vector": RetrievalReasonCode.EMPTY_VECTOR,
        "below_threshold": RetrievalReasonCode.BELOW_THRESHOLD,
        "top_k_exceeded": RetrievalReasonCode.TOP_K_EXCEEDED,
        "prompt_budget_exceeded": RetrievalReasonCode.PROMPT_BUDGET_EXCEEDED,
    }
    return mapping.get(name, RetrievalReasonCode.BELOW_THRESHOLD)


class RetrievalContext:
    """Context needed to execute retrieval for one run."""

    def __init__(
        self,
        task_id,
        run_id,
        request_id,
        semantic_query,
        effective_memory_mode,
        current_constraints,
        active_conflict_ids=None,
    ):
        self.task_id = task_id
        self.run_id = run_id
        self.request_id = request_id
        self.semantic_query = semantic_query
        self.effective_memory_mode = effective_memory_mode
        self.current_constraints = current_constraints
        self.active_conflict_ids = active_conflict_ids or []


def execute_retrieval(cards, ctx: RetrievalContext, trace_id: str) -> RetrievalResult:
    """Execute full retrieval pipeline on owner-filtered active cards."""
    result = RetrievalResult(
        trace_id=trace_id,
        request_id=ctx.request_id,
        task_id=ctx.task_id,
        run_id=ctx.run_id,
        retrieval_ms=0,
    )

    if not cards:
        return result

    # Hard filter each card
    passed = []
    for card in cards:
        ok, reasons = check_hard_filters(
            card, None, ctx.effective_memory_mode, ctx.current_constraints
        )
        if not ok:
            result.decisions.append(
                RetrievalDecision(
                    memory_id=card.id,
                    memory_version_id=card.current_version_id,
                    memory_status=card.status,
                    retrieved=False,
                    selected=False,
                    injected=False,
                    rank=None,
                    scope_match=None,
                    semantic_similarity=None,
                    provenance_confidence=None,
                    verified_effect=None,
                    recency=None,
                    final_score=None,
                    reason_codes=[_reason_code_str(r) for r in reasons],
                )
            )
        else:
            passed.append(card)

    if not passed:
        return result

    # TF-IDF
    query_text = normalize_text(ctx.semantic_query)
    q_ngrams = generate_ngrams(query_text)
    q_vec = build_vector(q_ngrams)

    if not q_vec:
        for card in passed:
            result.decisions.append(
                RetrievalDecision(
                    memory_id=card.id,
                    memory_version_id=card.current_version_id,
                    memory_status=card.status,
                    retrieved=True,
                    selected=False,
                    injected=False,
                    rank=None,
                    scope_match=None,
                    semantic_similarity=0.0,
                    provenance_confidence=None,
                    verified_effect=None,
                    recency=None,
                    final_score=0.0,
                    reason_codes=[RetrievalReasonCode.EMPTY_VECTOR],
                )
            )
        return result

    mem_docs = [build_memory_document(c) for c in passed]
    tfidf = compute_tfidf_vectors([query_text] + mem_docs)
    mem_vecs = tfidf[1:]

    scored = []
    for i, card in enumerate(passed):
        sim = cosine_similarity(q_vec, mem_vecs[i])
        cs_dict = (
            json.loads(card.scope_json) if isinstance(card.scope_json, str) else card.scope_json
        )
        scope = compute_scope_match(cs_dict, None)
        prov = min(card.source_trust, card.rule_confidence or 0, card.scope_confidence or 0)
        ve = compute_verified_effect(card.helpful_count, card.harmful_count, card.stale_count)
        rec = compute_recency(card.source_type, card.created_at)
        final = 0.25 * scope + 0.30 * sim + 0.15 * prov + 0.15 * ve + 0.15 * rec
        scored.append((card, sim, scope, prov, ve, rec, final))

    scored.sort(key=lambda x: (-x[6], -x[1], x[0].id))

    selected = []
    for item in scored:
        card, sim, scope, prov, ve, rec, final = item
        if final >= THRESHOLD and len(selected) < TOP_K:
            selected.append(item)

    # Decisions
    selected_ids = {c.id for c, *_ in selected}
    for card, sim, scope, prov, ve, rec, final in scored:
        is_sel = card.id in selected_ids
        rank = next((j + 1 for j, (s, *_) in enumerate(selected) if s.id == card.id), None)
        reasons = (
            [RetrievalReasonCode.SELECTED_ABOVE_THRESHOLD]
            if is_sel
            else [RetrievalReasonCode.BELOW_THRESHOLD]
        )
        result.decisions.append(
            RetrievalDecision(
                memory_id=card.id,
                memory_version_id=card.current_version_id,
                memory_status=card.status,
                retrieved=True,
                selected=is_sel,
                injected=False,
                rank=rank,
                scope_match=safe_round(scope),
                semantic_similarity=safe_round(sim),
                provenance_confidence=safe_round(prov),
                verified_effect=safe_round(ve),
                recency=safe_round(rec),
                final_score=safe_round(final),
                reason_codes=reasons,
            )
        )

    # Prompt budget
    if selected:
        block_texts = []
        for card, sim, scope, prov, ve, rec, final in selected:
            cs_dict = (
                json.loads(card.scope_json) if isinstance(card.scope_json, str) else card.scope_json
            )
            exc_list = (
                json.loads(card.exceptions_json)
                if isinstance(card.exceptions_json, str)
                else (card.exceptions_json or [])
            )
            when = card.trigger_text or _scope_summary(cs_dict)
            block_texts.append(
                compile_memory_block(
                    card.id,
                    card.current_version_id,
                    final,
                    when,
                    card.rule,
                    card.avoid,
                    ", ".join(exc_list),
                )
            )

        section, tokens, h = compile_prompt_section(block_texts)
        if tokens <= 300:
            result.memory_context = section
            result.memory_tokens_estimated = tokens
            result.prompt_section_hash = h
            for d in result.decisions:
                if d.selected:
                    d.injected = True
        else:
            for d in result.decisions:
                if d.selected and not d.injected:
                    d.reason_codes.append(RetrievalReasonCode.PROMPT_BUDGET_EXCEEDED)

    return result
