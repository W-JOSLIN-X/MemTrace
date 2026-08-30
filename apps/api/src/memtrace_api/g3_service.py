"""Transactional G3 retrieval, receipt, verification, and projection services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from memtrace_api.db_models import (
    MemoryCardModel,
    MemoryRelationModel,
    MemoryUsageModel,
    MemoryVerificationJobModel,
    MemoryVersionModel,
    RetrievalDecisionModel,
    RetrievalTraceModel,
)
from memtrace_api.events import EventType
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.repositories import TaskRepository, UserContext
from memtrace_api.retrieval import ALGORITHM_VERSION, RETRIEVAL_MODE, THRESHOLD, TOP_K
from memtrace_api.retrieval_executor import RetrievalContext, execute_retrieval, to_response
from memtrace_api.schemas import (
    MemoryUsageResponse,
    RetrievalDecisionResponse,
    RetrievalReasonCode,
    RetrievalTraceResponse,
    TaskFingerprint,
    VerificationStatus,
    utc_now,
)
from memtrace_api.verifier import verify_exact_substring


@dataclass(frozen=True, slots=True)
class PersistedG3Event:
    event_type: EventType
    event_seq: int
    data: dict[str, Any]


@dataclass(slots=True)
class RetrievalExecution:
    memory_context: str | None
    usage_ids: tuple[str, ...]
    trace: RetrievalTraceResponse
    usages: list[MemoryUsageResponse]
    events: list[PersistedG3Event]


def execute_and_persist_retrieval(
    session: Session,
    user_ctx: UserContext,
    *,
    request_id: str,
    task_id: str,
    run_id: str,
    fingerprint: TaskFingerprint,
    effective_memory_mode: str,
) -> RetrievalExecution:
    cards: list[MemoryCardModel] = []
    conflict_ids: set[str] = set()
    if effective_memory_mode != "off" and not fingerprint.current_constraints.memory_disabled:
        cards = list(
            session.execute(
                select(MemoryCardModel)
                .options(selectinload(MemoryCardModel.versions))
                .where(
                    and_(
                        MemoryCardModel.owner_id == user_ctx.user_id,
                        or_(
                            MemoryCardModel.schema_version.is_(None),
                            MemoryCardModel.schema_version != "2.0",
                        ),
                    )
                )
                .order_by(MemoryCardModel.id.asc())
            )
            .scalars()
            .all()
        )
        relations = session.execute(
            select(MemoryRelationModel).where(
                and_(
                    MemoryRelationModel.owner_id == user_ctx.user_id,
                    MemoryRelationModel.relation_type == "conflicts_with",
                )
            )
        ).scalars()
        for relation in relations:
            conflict_ids.update((relation.from_memory_id, relation.to_memory_id))

    trace_id = new_prefixed_ulid("trace")
    result = execute_retrieval(
        cards,
        RetrievalContext(
            task_id=task_id,
            run_id=run_id,
            request_id=request_id,
            fingerprint=fingerprint,
            effective_memory_mode=effective_memory_mode,
            current_constraints=fingerprint.current_constraints,
            active_conflict_ids=frozenset(conflict_ids),
        ),
        trace_id,
    )
    response = to_response(result)
    trace_row = RetrievalTraceModel(
        id=trace_id,
        owner_id=user_ctx.user_id,
        request_id=request_id,
        task_id=task_id,
        run_id=run_id,
        retrieval_mode=RETRIEVAL_MODE,
        algorithm_version=ALGORITHM_VERSION,
        threshold=THRESHOLD,
        top_k=TOP_K,
        candidate_count=response.candidate_count,
        retrieved_count=response.retrieved_count,
        selected_count=response.selected_count,
        injected_count=response.injected_count,
        decisions_json="[]",
        retrieval_ms=response.retrieval_ms,
        memory_chars=response.memory_chars,
        memory_tokens_estimated=response.memory_tokens_estimated,
        provider_prompt_tokens_actual=None,
        prompt_section_hash=response.prompt_section_hash,
        reason_codes_json=json.dumps([reason.value for reason in response.reason_codes]),
        created_at=response.created_at,
        updated_at=response.updated_at,
    )
    session.add(trace_row)
    session.flush([trace_row])

    card_by_id = {card.id: card for card in cards}
    usage_rows: list[MemoryUsageModel] = []
    decision_by_id = {decision.memory_id: decision for decision in result.decisions}
    for decision in result.decisions:
        session.add(
            RetrievalDecisionModel(
                id=new_prefixed_ulid("rdec"),
                owner_id=user_ctx.user_id,
                retrieval_trace_id=trace_id,
                memory_id=decision.memory_id,
                memory_version_id=decision.memory_version_id,
                memory_status=decision.memory_status,
                retrieved=decision.retrieved,
                selected=decision.selected,
                injected=decision.injected,
                rank=decision.rank,
                scope_match=decision.scope_match,
                semantic_similarity=decision.semantic_similarity,
                provenance_confidence=decision.provenance_confidence,
                verified_effect=decision.verified_effect,
                recency=decision.recency,
                final_score=decision.final_score,
                reason_codes_json=json.dumps([reason.value for reason in decision.reason_codes]),
                created_at=response.created_at,
            )
        )
        card = card_by_id.get(decision.memory_id)
        if card is not None and decision.retrieved:
            card.retrieved_count += 1
        if card is not None and decision.injected:
            card.injected_count += 1
            card.last_used_at = response.created_at
        if decision.selected:
            usage_rows.append(
                MemoryUsageModel(
                    id=new_prefixed_ulid("usage"),
                    owner_id=user_ctx.user_id,
                    retrieval_trace_id=trace_id,
                    task_id=task_id,
                    run_id=run_id,
                    memory_id=decision.memory_id,
                    memory_version_id=decision.memory_version_id,
                    rank=decision.rank,
                    retrieved=True,
                    selected=True,
                    injected=decision.injected,
                    estimated_tokens=decision.estimated_tokens,
                    verification_status=(
                        VerificationStatus.PENDING.value
                        if decision.injected
                        else VerificationStatus.UNKNOWN.value
                    ),
                    verification_method=None,
                    evidence_excerpt=None,
                    user_effect=None,
                    created_at=response.created_at,
                    updated_at=response.updated_at,
                )
            )
    session.add_all(usage_rows)
    session.flush()

    task_repo = TaskRepository(user_ctx, session)
    events: list[PersistedG3Event] = []
    completed_data = {
        "trace_id": trace_id,
        "mode": RETRIEVAL_MODE,
        "algorithm_version": ALGORITHM_VERSION,
        "candidate_count": response.candidate_count,
        "retrieved_count": response.retrieved_count,
        "selected_count": response.selected_count,
        "injected_count": response.injected_count,
        "threshold": THRESHOLD,
        "top_k": TOP_K,
        "retrieval_ms": response.retrieval_ms,
        "memory_chars": response.memory_chars,
        "estimated_tokens": response.memory_tokens_estimated,
        "prompt_section_hash": response.prompt_section_hash,
    }
    completed_seq = task_repo.allocate_next_event_seq(task_id)
    task_repo.append_event(
        stream_type="task",
        stream_id=task_id,
        seq=completed_seq,
        event_type=EventType.MEMORY_RETRIEVAL_COMPLETED.value,
        metadata=completed_data,
    )
    events.append(
        PersistedG3Event(EventType.MEMORY_RETRIEVAL_COMPLETED, completed_seq, completed_data)
    )
    for usage in usage_rows:
        if not usage.injected:
            continue
        decision = decision_by_id[usage.memory_id]
        injected_data = {
            "usage_id": usage.id,
            "trace_id": trace_id,
            "memory_id": usage.memory_id,
            "memory_version_id": usage.memory_version_id,
            "rank": usage.rank,
            "estimated_tokens": usage.estimated_tokens,
            "prompt_section_hash": response.prompt_section_hash,
        }
        injected_seq = task_repo.allocate_next_event_seq(task_id)
        task_repo.append_event(
            stream_type="task",
            stream_id=task_id,
            seq=injected_seq,
            event_type=EventType.MEMORY_INJECTED.value,
            metadata=injected_data,
        )
        events.append(PersistedG3Event(EventType.MEMORY_INJECTED, injected_seq, injected_data))
        decision.injected = True

    return RetrievalExecution(
        memory_context=result.memory_context,
        usage_ids=tuple(usage.id for usage in usage_rows if usage.injected),
        trace=response,
        usages=[usage_projection(usage, request_id=request_id) for usage in usage_rows],
        events=events,
    )


def verify_injected_usages(
    session: Session,
    user_ctx: UserContext,
    *,
    request_id: str,
    task_id: str,
    run_id: str,
    output: str,
) -> tuple[list[MemoryUsageResponse], list[PersistedG3Event]]:
    usages = list(
        session.execute(
            select(MemoryUsageModel).where(
                and_(
                    MemoryUsageModel.owner_id == user_ctx.user_id,
                    MemoryUsageModel.task_id == task_id,
                    MemoryUsageModel.run_id == run_id,
                    MemoryUsageModel.injected.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    events: list[PersistedG3Event] = []
    task_repo = TaskRepository(user_ctx, session)
    for usage in usages:
        existing = session.execute(
            select(MemoryVerificationJobModel).where(
                MemoryVerificationJobModel.memory_usage_id == usage.id
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status == "completed":
            continue
        job = existing or MemoryVerificationJobModel(
            id=new_prefixed_ulid("vjob"),
            owner_id=user_ctx.user_id,
            memory_usage_id=usage.id,
            status="running",
            attempt=0,
            error_code=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        if existing is None:
            session.add(job)
        version = session.execute(
            select(MemoryVersionModel).where(
                and_(
                    MemoryVersionModel.id == usage.memory_version_id,
                    MemoryVersionModel.owner_id == user_ctx.user_id,
                )
            )
        ).scalar_one()
        status, excerpt = verify_exact_substring(output, version.rule, version.avoid)
        usage.verification_status = status
        usage.verification_method = "exact_substring"
        usage.evidence_excerpt = excerpt
        usage.updated_at = utc_now()
        job.status = "completed"
        job.updated_at = utc_now()
        card = session.execute(
            select(MemoryCardModel).where(
                and_(
                    MemoryCardModel.id == usage.memory_id,
                    MemoryCardModel.owner_id == user_ctx.user_id,
                )
            )
        ).scalar_one()
        if status == VerificationStatus.APPLIED.value:
            card.verified_applied_count += 1
        data = {
            "usage_id": usage.id,
            "memory_id": usage.memory_id,
            "memory_version_id": usage.memory_version_id,
            "verification_status": status,
            "verification_method": "exact_substring",
            "evidence_present": excerpt is not None,
        }
        seq = task_repo.allocate_next_event_seq(task_id)
        task_repo.append_event(
            stream_type="task",
            stream_id=task_id,
            seq=seq,
            event_type=EventType.MEMORY_USAGE_VERIFIED.value,
            metadata=data,
        )
        events.append(PersistedG3Event(EventType.MEMORY_USAGE_VERIFIED, seq, data))
    session.flush()
    return (
        [usage_projection(usage, request_id=request_id) for usage in usages],
        events,
    )


def mark_injected_unknown(session: Session, user_ctx: UserContext, *, run_id: str) -> None:
    for usage in session.execute(
        select(MemoryUsageModel).where(
            and_(
                MemoryUsageModel.owner_id == user_ctx.user_id,
                MemoryUsageModel.run_id == run_id,
                MemoryUsageModel.injected.is_(True),
                MemoryUsageModel.verification_status == VerificationStatus.PENDING.value,
            )
        )
    ).scalars():
        usage.verification_status = VerificationStatus.UNKNOWN.value
        usage.updated_at = utc_now()


def update_actual_prompt_tokens(
    session: Session,
    user_ctx: UserContext,
    *,
    run_id: str,
    prompt_tokens: int | None,
) -> None:
    if prompt_tokens is None:
        return
    trace = session.execute(
        select(RetrievalTraceModel).where(
            and_(
                RetrievalTraceModel.owner_id == user_ctx.user_id,
                RetrievalTraceModel.run_id == run_id,
            )
        )
    ).scalar_one_or_none()
    if trace is not None:
        trace.provider_prompt_tokens_actual = prompt_tokens
        trace.updated_at = utc_now()


def load_task_g3(
    session: Session,
    user_ctx: UserContext,
    *,
    request_id: str,
    task_id: str,
    run_id: str,
) -> tuple[RetrievalTraceResponse | None, list[MemoryUsageResponse]]:
    trace = session.execute(
        select(RetrievalTraceModel).where(
            and_(
                RetrievalTraceModel.owner_id == user_ctx.user_id,
                RetrievalTraceModel.task_id == task_id,
                RetrievalTraceModel.run_id == run_id,
            )
        )
    ).scalar_one_or_none()
    usages = list(
        session.execute(
            select(MemoryUsageModel)
            .where(
                and_(
                    MemoryUsageModel.owner_id == user_ctx.user_id,
                    MemoryUsageModel.task_id == task_id,
                    MemoryUsageModel.run_id == run_id,
                )
            )
            .order_by(MemoryUsageModel.rank.asc(), MemoryUsageModel.memory_id.asc())
        )
        .scalars()
        .all()
    )
    return (
        trace_projection(session, user_ctx, trace) if trace is not None else None,
        [usage_projection(usage, request_id=request_id) for usage in usages],
    )


def trace_projection(
    session: Session,
    user_ctx: UserContext,
    trace: RetrievalTraceModel,
) -> RetrievalTraceResponse:
    decisions = list(
        session.execute(
            select(RetrievalDecisionModel)
            .where(
                and_(
                    RetrievalDecisionModel.owner_id == user_ctx.user_id,
                    RetrievalDecisionModel.retrieval_trace_id == trace.id,
                )
            )
            .order_by(
                RetrievalDecisionModel.rank.asc().nullslast(),
                RetrievalDecisionModel.memory_id.asc(),
            )
        )
        .scalars()
        .all()
    )
    return RetrievalTraceResponse(
        request_id=trace.request_id,
        retrieval_trace_id=trace.id,
        task_id=trace.task_id,
        run_id=trace.run_id,
        retrieval_mode=trace.retrieval_mode,
        algorithm_version=trace.algorithm_version,
        threshold=trace.threshold,
        top_k=trace.top_k,
        candidate_count=trace.candidate_count,
        retrieved_count=trace.retrieved_count,
        selected_count=trace.selected_count,
        injected_count=trace.injected_count,
        decisions=[decision_projection(decision) for decision in decisions],
        retrieval_ms=trace.retrieval_ms,
        memory_chars=trace.memory_chars,
        memory_tokens_estimated=trace.memory_tokens_estimated,
        provider_prompt_tokens_actual=trace.provider_prompt_tokens_actual,
        prompt_section_hash=trace.prompt_section_hash,
        reason_codes=json.loads(trace.reason_codes_json),
        created_at=trace.created_at,
        updated_at=trace.updated_at,
    )


def decision_projection(row: RetrievalDecisionModel) -> RetrievalDecisionResponse:
    return RetrievalDecisionResponse(
        memory_id=row.memory_id,
        memory_version_id=row.memory_version_id,
        memory_status=row.memory_status,
        retrieved=row.retrieved,
        selected=row.selected,
        injected=row.injected,
        rank=row.rank,
        scope_match=_round(row.scope_match),
        semantic_similarity=_round(row.semantic_similarity),
        provenance_confidence=_round(row.provenance_confidence),
        verified_effect=_round(row.verified_effect),
        recency=_round(row.recency),
        final_score=_round(row.final_score),
        reason_codes=[RetrievalReasonCode(value) for value in json.loads(row.reason_codes_json)],
    )


def usage_projection(row: MemoryUsageModel, *, request_id: str) -> MemoryUsageResponse:
    return MemoryUsageResponse(
        request_id=request_id,
        usage_id=row.id,
        retrieval_trace_id=row.retrieval_trace_id,
        task_id=row.task_id,
        run_id=row.run_id,
        memory_id=row.memory_id,
        memory_version_id=row.memory_version_id,
        rank=row.rank,
        retrieved=row.retrieved,
        selected=row.selected,
        injected=row.injected,
        estimated_tokens=row.estimated_tokens,
        verification_status=row.verification_status,
        verification_method=row.verification_method,
        evidence_excerpt=row.evidence_excerpt,
        user_effect=row.user_effect,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def recover_verification_jobs(session: Session) -> int:
    recovered = 0
    jobs = list(
        session.execute(
            select(MemoryVerificationJobModel).where(
                MemoryVerificationJobModel.status.in_(("pending", "running"))
            )
        )
        .scalars()
        .all()
    )
    for job in jobs:
        if job.status == "running" and job.attempt >= 2:
            job.status = "failed"
            job.error_code = "MEMORY_VERIFIER_INTERRUPTED"
        else:
            job.status = "pending"
            if job.attempt < 2:
                job.attempt += 1
        job.updated_at = utc_now()
        usage = session.get(MemoryUsageModel, job.memory_usage_id)
        if usage is not None and job.status == "failed":
            usage.verification_status = VerificationStatus.UNKNOWN.value
            usage.updated_at = utc_now()
        recovered += 1
    return recovered


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)
