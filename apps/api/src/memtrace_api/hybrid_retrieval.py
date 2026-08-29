"""Day 6 v2.0.0: Hybrid retrieval — combines TF-IDF recall with LLM applicability judge."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from memtrace_api.config import Settings
from memtrace_api.db_models import MemoryCardModel, MemoryEvidenceModel, MemoryVersionModel
from memtrace_api.judges import ApplicabilityJudge
from memtrace_api.retrieval import (
    ALGORITHM_VERSION,
    THRESHOLD,
    TOP_K,
    cosine_similarity,
    compute_scope_match,
    check_hard_filters,
    build_memory_document,
    normalize_text,
    generate_ngrams,
    compute_tfidf_vectors,
)

logger = logging.getLogger(__name__)

# Recall more candidates than we need for LLM judge
RECALL_MULTIPLIER = 5
MAX_JUDGE_CANDIDATES = 20


@dataclass(slots=True, frozen=True)
class HybridCandidate:
    """Single candidate memory for LLM judge."""
    card_id: str
    kind: str
    content: str
    applies_when: str
    tfidf_score: float
    scope_score: float
    combined_score: float


@dataclass(slots=True, frozen=True)
class HybridResult:
    """Result of hybrid retrieval."""
    selected_ids: list[str]
    rejected_ids: list[str]
    total_recalled: int
    total_judged: int


def _fetch_candidates(
    session: Session,
    owner_id: str,
    task_text: str,
    limit: int = MAX_JUDGE_CANDIDATES,
) -> list[tuple[Any, float]]:
    """Fetch candidate memories using TF-IDF recall (hard-filtered, owner-scoped)."""
    # Hard filters
    hard_filtered = check_hard_filters(task_text)
    if not hard_filtered:
        return []

    # Normalize task text
    task_normalized = normalize_text(task_text)
    task_ngrams = generate_ngrams(task_normalized)

    if not task_ngrams:
        return []

    # Fetch active memories for this owner
    rows = session.execute(
        select(MemoryCardModel, MemoryVersionModel)
        .join(
            MemoryVersionModel,
            MemoryCardModel.current_version_id == MemoryVersionModel.id,
        )
        .where(
            and_(
                MemoryCardModel.owner_id == owner_id,
                MemoryCardModel.status == "active",
                MemoryCardModel.review_status == "active",
            )
        )
        .order_by(MemoryCardModel.updated_at.desc())
        .limit(200)
    ).all()

    if not rows:
        return []

    # Build documents
    cards = []
    documents = []
    for card, version in rows:
        doc = build_memory_document(card, version)
        cards.append((card, version))
        documents.append(doc)

    if not documents:
        return []

    # Compute TF-IDF similarity
    task_vec = compute_tfidf_vectors([task_normalized])[0]
    doc_vecs = compute_tfidf_vectors(documents)

    scored = []
    task_ngram_set = set(task_ngrams)
    for (card, version), doc_vec in zip(cards, doc_vecs):
        if not doc_vec:
            continue
        tfidf_score = cosine_similarity(task_vec, doc_vec)
        if tfidf_score < THRESHOLD * 0.5:  # Lower threshold for recall
            continue
        scope = card.scope_json if isinstance(card.scope_json, dict) else {}
        scope_score = compute_scope_match(scope, hard_filtered)
        combined = tfidf_score * 0.7 + scope_score * 0.3
        scored.append((card, version, tfidf_score, scope_score, combined))

    scored.sort(key=lambda x: x[4], reverse=True)
    return [
        (card_version[0], card_version[1], s[2], s[3], s[4])
        for s, card_version in zip(scored[:limit], [(c, v) for c, v, _, _, _ in scored[:limit]])
    ]


def recall_and_judge(
    session: Session,
    owner_id: str,
    task_text: str,
    judge: ApplicabilityJudge | None = None,
    max_results: int = TOP_K,
) -> HybridResult:
    """Run hybrid retrieval: TF-IDF recall + LLM applicability judge.

    Returns selected IDs and rejected IDs.
    """
    judge = judge or ApplicabilityJudge()

    # Step 1: Recall candidates via TF-IDF
    candidates = _fetch_candidates(session, owner_id, task_text)
    if not candidates:
        return HybridResult(
            selected_ids=[],
            rejected_ids=[],
            total_recalled=0,
            total_judged=0,
        )

    # Step 2: LLM Judge applicability
    selected_ids: list[str] = []
    rejected_ids: list[str] = []
    judged = 0

    for card, version, tfidf_score, scope_score, combined_score in candidates:
        if judged >= MAX_JUDGE_CANDIDATES:
            break

        memory_data = {
            "id": card.id,
            "kind": card.kind,
            "content": version.content or card.content or "",
            "applies_when": version.applies_when or card.applies_when or "",
        }

        # Run judge (synchronous call in thread would be better for production)
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                judge.judge(
                    task_text=task_text,
                    constraints="",
                    candidate_memory=memory_data,
                    nearby_memories=[],
                )
            )
            loop.close()
        except Exception as e:
            logger.warning(f"hybrid_judge_error", exc_info=e)
            result = None

        if result and result.result == "applicable":
            selected_ids.append(card.id)
        elif result and result.result in ("current_instruction_override", "conflict"):
            rejected_ids.append(card.id)

        judged += 1

    # Limit to max_results
    selected_ids = selected_ids[:max_results]

    return HybridResult(
        selected_ids=selected_ids,
        rejected_ids=rejected_ids,
        total_recalled=len(candidates),
        total_judged=judged,
    )
