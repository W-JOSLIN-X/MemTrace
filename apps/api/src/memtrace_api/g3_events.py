"""G3 retrieval, usage, and lifecycle event payloads."""

from __future__ import annotations

from typing import Any

from memtrace_api.events import (
    ContractModel,
    EventType,
    RetrievalTraceId,
    UsageId,
    VerificationStatus,
    make_event,
    serialize_sse,
)


def create_retrieval_completed_event(
    *,
    task_id: str,
    run_id: str,
    retrieval_trace_id: str,
    retrieval_mode: str,
    algorithm_version: str,
    candidate_count: int,
    retrieved_count: int,
    selected_count: int,
    injected_count: int,
    threshold: float,
    top_k: int,
    retrieval_ms: int,
    memory_chars: int,
    memory_tokens_estimated: int,
    prompt_section_hash: str | None = None,
) -> bytes:
    """Create and serialize a memory.retrieval.completed event."""
    event = make_event(
        event_type=EventType.MEMORY_RETRIEVAL_COMPLETED,
        event_seq=None,
        task_id=task_id,
        run_id=run_id,
        data={
            "retrieval_trace_id": retrieval_trace_id,
            "retrieval_mode": retrieval_mode,
            "algorithm_version": algorithm_version,
            "candidate_count": candidate_count,
            "retrieved_count": retrieved_count,
            "selected_count": selected_count,
            "injected_count": injected_count,
            "threshold": threshold,
            "top_k": top_k,
            "retrieval_ms": retrieval_ms,
            "memory_chars": memory_chars,
            "memory_tokens_estimated": memory_tokens_estimated,
            "prompt_section_hash": prompt_section_hash,
        },
    )
    return serialize_sse(event)


def create_memory_injected_event(
    *,
    task_id: str,
    run_id: str,
    usage_id: str,
    retrieval_trace_id: str,
    memory_id: str,
    memory_version_id: str,
    rank: int,
    estimated_tokens: int,
    prompt_section_hash: str | None = None,
) -> bytes:
    """Create and serialize a memory.injected event."""
    event = make_event(
        event_type=EventType.MEMORY_INJECTED,
        event_seq=None,
        task_id=task_id,
        run_id=run_id,
        data={
            "usage_id": usage_id,
            "retrieval_trace_id": retrieval_trace_id,
            "memory_id": memory_id,
            "memory_version_id": memory_version_id,
            "rank": rank,
            "estimated_tokens": estimated_tokens,
            "prompt_section_hash": prompt_section_hash,
        },
    )
    return serialize_sse(event)


def create_memory_usage_verified_event(
    *,
    task_id: str,
    run_id: str,
    usage_id: str,
    memory_id: str,
    memory_version_id: str,
    verification_status: str,
    verification_method: str | None = None,
    evidence_present: bool = False,
) -> bytes:
    """Create and serialize a memory.usage.verified event."""
    event = make_event(
        event_type=EventType.MEMORY_USAGE_VERIFIED,
        event_seq=None,
        task_id=task_id,
        run_id=run_id,
        data={
            "usage_id": usage_id,
            "memory_id": memory_id,
            "memory_version_id": memory_version_id,
            "verification_status": verification_status,
            "verification_method": verification_method,
            "evidence_present": evidence_present,
        },
    )
    return serialize_sse(event)


def create_memory_usage_feedback_event(
    *,
    task_id: str,
    run_id: str,
    usage_id: str,
    memory_id: str,
    user_effect: str,
) -> bytes:
    """Create and serialize a memory.usage.feedback.recorded event."""
    event = make_event(
        event_type=EventType.MEMORY_USAGE_FEEDBACK_RECORDED,
        event_seq=None,
        task_id=task_id,
        run_id=run_id,
        data={
            "usage_id": usage_id,
            "memory_id": memory_id,
            "user_effect": user_effect,
        },
    )
    return serialize_sse(event)
