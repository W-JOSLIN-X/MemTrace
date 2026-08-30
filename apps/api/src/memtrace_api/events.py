"""Typed G0 event envelopes and SSE serialization."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, StringConstraints, model_validator

from memtrace_api.schemas import (
    ArtifactType,
    AsyncErrorCode,
    ClassificationReasonCode,
    CodeSource,
    ContractModel,
    Disposition,
    Domain,
    ErrorId,
    EvidenceId,
    FeedbackId,
    FeedbackType,
    FingerprintId,
    MemoryCardStatus,
    MemoryId,
    MemoryJobErrorCode,
    MemoryJobId,
    MemoryJobStage,
    MemoryReflectionJobId,
    MemoryVersionId,
    MessageId,
    PlanId,
    ProgrammingLanguage,
    ProviderMode,
    RetrievalTraceId,
    RunId,
    TaskId,
    TaskType,
    ToolCallId,
    ToolResultId,
    UsageId,
    UserEffect,
    VerificationStatus,
    utc_now,
)


class EventType(StrEnum):
    TASK_CREATED = "task.created"
    TASK_STAGE = "task.stage"
    TASK_FINGERPRINTED = "task.fingerprinted"
    TASK_DELETED = "task.deleted"
    MEMORY_RETRIEVAL_STARTED = "memory.retrieval.started"
    MEMORY_RETRIEVAL_COMPLETED = "memory.retrieval.completed"
    AGENT_PLAN_PUBLISHED = "agent.plan.published"
    TOOL_CALLED = "tool.called"
    TOOL_RESULT = "tool.result"
    AGENT_CHUNK = "agent.chunk"
    RUN_METRICS = "run.metrics"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    ERROR = "error"
    STREAM_DONE = "stream.done"
    FEEDBACK_RECORDED = "feedback.recorded"
    MEMORY_EXTRACTION_STAGE = "memory.extraction.stage"
    MEMORY_CANDIDATE_CREATED = "memory.candidate.created"
    MEMORY_ADMISSION_RESOLVED = "memory.admission.resolved"
    MEMORY_JOB_FAILED = "memory.job.failed"
    MEMORY_INJECTED = "memory.injected"
    MEMORY_USAGE_VERIFIED = "memory.usage.verified"
    MEMORY_USAGE_FEEDBACK_RECORDED = "memory.usage.feedback.recorded"
    MEMORY_LIFECYCLE_CHANGED = "memory.lifecycle.changed"
    MEMORY_CONFLICT_DETECTED = "memory.conflict.detected"
    MEMORY_CONFLICT_RESOLVED = "memory.conflict.resolved"
    MEMORY_PACK_PREVIEWED = "memory.pack.previewed"
    MEMORY_PACK_COMMITTED = "memory.pack.committed"
    MEMORY_ANALYSIS_STARTED = "memory.analysis.started"
    MEMORY_ANALYSIS_COMPLETED = "memory.analysis.completed"
    MEMORY_EFFECT_JUDGED = "memory.effect.judged"


PERSISTENT_EVENT_TYPES = frozenset(
    {
        EventType.TASK_CREATED,
        EventType.TASK_STAGE,
        EventType.TASK_FINGERPRINTED,
        EventType.TASK_DELETED,
        EventType.MEMORY_RETRIEVAL_COMPLETED,
        EventType.AGENT_PLAN_PUBLISHED,
        EventType.TOOL_CALLED,
        EventType.TOOL_RESULT,
        EventType.RUN_METRICS,
        EventType.RUN_COMPLETED,
        EventType.RUN_FAILED,
        EventType.ERROR,
        EventType.STREAM_DONE,
        EventType.FEEDBACK_RECORDED,
        EventType.MEMORY_EXTRACTION_STAGE,
        EventType.MEMORY_CANDIDATE_CREATED,
        EventType.MEMORY_ADMISSION_RESOLVED,
        EventType.MEMORY_JOB_FAILED,
        EventType.MEMORY_INJECTED,
        EventType.MEMORY_USAGE_VERIFIED,
        EventType.MEMORY_USAGE_FEEDBACK_RECORDED,
        EventType.MEMORY_LIFECYCLE_CHANGED,
        EventType.MEMORY_CONFLICT_DETECTED,
        EventType.MEMORY_CONFLICT_RESOLVED,
        EventType.MEMORY_PACK_PREVIEWED,
        EventType.MEMORY_PACK_COMMITTED,
        EventType.MEMORY_ANALYSIS_STARTED,
        EventType.MEMORY_ANALYSIS_COMPLETED,
        EventType.MEMORY_EFFECT_JUDGED,
    }
)


class TaskCreatedPayload(ContractModel):
    task_status: Literal["active"] = "active"
    run_status: Literal["queued"] = "queued"


class TaskStagePayload(ContractModel):
    stage: Literal[
        "fingerprinting", "retrieving", "planning", "tool_running", "generating", "failed"
    ]
    progress_label: Literal[
        "fingerprinting_task",
        "retrieving_memory",
        "publishing_plan",
        "running_static_tool",
        "generating_answer",
        "run_failed",
    ]


class TaskFingerprintedPayload(ContractModel):
    fingerprint_id: FingerprintId
    domain: Domain
    classification_source: Literal["auto_rule_v1"] = "auto_rule_v1"
    classification_confidence: float = Field(ge=0, le=1)
    classification_reasons: Annotated[list[ClassificationReasonCode], Field(max_length=5)]
    task_type: TaskType
    artifact_type: ArtifactType
    language: ProgrammingLanguage


class MemoryRetrievalStartedPayload(ContractModel):
    retrieval_mode: str = "tfidf"


class AgentPlanPublishedPayload(ContractModel):
    plan_id: PlanId
    goal_code: Literal["analyze_code", "answer_question", "explain_concept", "other"]
    memory_summary_code: Literal["no_memory_selected", "memory_selected"]
    next_action_code: Literal["python_ast_check", "generate_directly"]


class SafeToolArgsSummary(ContractModel):
    language: Literal["python"] = "python"
    code_source: CodeSource
    code_bytes: int = Field(ge=1, le=102_400)


class ToolCalledPayload(ContractModel):
    tool_call_id: ToolCallId
    tool_name: Literal["python_ast_check"] = "python_ast_check"
    reason_code: Literal["python_code_detected"] = "python_code_detected"
    args_summary: SafeToolArgsSummary


class ToolResultPayload(ContractModel):
    tool_call_id: ToolCallId
    tool_name: Literal["python_ast_check"] = "python_ast_check"
    status: Literal["succeeded", "failed"]
    latency_ms: float = Field(ge=0)
    result_ref: ToolResultId | None


ChunkDelta = Annotated[str, StringConstraints(min_length=1, max_length=32_768)]


class AgentChunkPayload(ContractModel):
    run_id: RunId
    chunk_seq: int = Field(ge=1)
    start_offset: int = Field(ge=0, le=262_144)
    end_offset: int = Field(ge=1, le=262_144)
    offset_unit: Literal["utf8_bytes"] = "utf8_bytes"
    delta: ChunkDelta

    @model_validator(mode="after")
    def offset_matches_delta(self) -> AgentChunkPayload:
        if self.end_offset != self.start_offset + len(self.delta.encode("utf-8")):
            raise ValueError("chunk offsets must use UTF-8 bytes")
        return self


class RunMetricsPayload(ContractModel):
    provider: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    model: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    provider_mode: ProviderMode
    first_token_ms: float | None = Field(default=None, ge=0)
    total_ms: float | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    token_source: Literal["actual", "unavailable", "mock"]

    @model_validator(mode="after")
    def tokens_match_source(self) -> RunMetricsPayload:
        if self.token_source == "unavailable":
            if self.prompt_tokens is not None or self.output_tokens is not None:
                raise ValueError("unavailable token counts must be null")
        elif self.prompt_tokens is None or self.output_tokens is None:
            raise ValueError("actual and mock token counts are required")
        return self


class RunCompletedPayload(ContractModel):
    status: Literal["succeeded"] = "succeeded"
    message_id: MessageId
    end_offset: int = Field(ge=0, le=262_144)
    offset_unit: Literal["utf8_bytes"] = "utf8_bytes"


class RunFailedPayload(ContractModel):
    status: Literal["failed"] = "failed"
    error_code: AsyncErrorCode
    retryable: bool
    partial_message_id: MessageId | None
    end_offset: int = Field(ge=0, le=262_144)
    offset_unit: Literal["utf8_bytes"] = "utf8_bytes"


class ErrorPayload(ContractModel):
    error_id: ErrorId
    code: AsyncErrorCode
    message: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    retryable: bool


class StreamDonePayload(ContractModel):
    status: Literal["succeeded", "failed"]
    final_snapshot_required: Literal[True] = True


class FeedbackRecordedPayload(ContractModel):
    feedback_id: FeedbackId
    memory_job_id: MemoryJobId
    feedback_type: FeedbackType


class MemoryExtractionStagePayload(ContractModel):
    memory_job_id: MemoryJobId
    stage: MemoryJobStage


class MemoryCandidateCreatedPayload(ContractModel):
    memory_job_id: MemoryJobId
    memory_id: MemoryId
    evidence_id: EvidenceId
    ordinal: int = Field(ge=0, le=2)


class MemoryAdmissionResolvedPayload(ContractModel):
    memory_id: MemoryId
    old_status: MemoryCardStatus
    new_status: MemoryCardStatus
    memory_version_id: MemoryVersionId | None = None
    disposition: Disposition


class MemoryJobFailedPayload(ContractModel):
    memory_job_id: MemoryJobId
    stage: MemoryJobStage
    error_code: MemoryJobErrorCode
    retryable: bool


class MemoryRetrievalCompletedPayload(ContractModel):
    trace_id: RetrievalTraceId
    mode: str
    algorithm_version: Literal["char_tfidf_v1"] = "char_tfidf_v1"
    candidate_count: int = Field(ge=0)
    retrieved_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    injected_count: int = Field(ge=0)
    threshold: float = Field(ge=0, le=1)
    top_k: int = Field(gt=0)
    retrieval_ms: int = Field(ge=0)
    memory_chars: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    prompt_section_hash: str | None = None


class MemoryInjectedPayload(ContractModel):
    usage_id: UsageId
    trace_id: RetrievalTraceId
    memory_id: MemoryId
    memory_version_id: MemoryVersionId
    rank: int = Field(ge=1)
    estimated_tokens: int = Field(ge=0)
    prompt_section_hash: str | None = None


class MemoryUsageVerifiedPayload(ContractModel):
    usage_id: UsageId
    memory_id: MemoryId
    memory_version_id: MemoryVersionId
    verification_status: VerificationStatus
    verification_method: Literal["exact_substring", "structured_provider"] | None = None
    evidence_present: bool


class MemoryUsageFeedbackRecordedPayload(ContractModel):
    usage_id: UsageId
    memory_id: MemoryId
    user_effect: UserEffect


class MemoryAnalysisStartedPayload(ContractModel):
    job_id: MemoryReflectionJobId
    task_id: TaskId
    run_id: RunId
    status: Literal["running"]


class MemoryAnalysisCompletedPayload(ContractModel):
    job_id: MemoryReflectionJobId
    task_id: TaskId
    run_id: RunId
    status: Literal["completed", "failed"]
    reason_code: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class MemoryEffectJudgedPayload(ContractModel):
    memory_id: MemoryId
    run_id: RunId
    judgment: Literal["applied", "violated", "not_observable", "unknown"]
    reason_code: Annotated[str, StringConstraints(min_length=1, max_length=64)]


EventPayload: TypeAlias = (
    TaskCreatedPayload
    | TaskStagePayload
    | TaskFingerprintedPayload
    | MemoryRetrievalStartedPayload
    | MemoryRetrievalCompletedPayload
    | AgentPlanPublishedPayload
    | ToolCalledPayload
    | ToolResultPayload
    | AgentChunkPayload
    | RunMetricsPayload
    | RunCompletedPayload
    | RunFailedPayload
    | ErrorPayload
    | StreamDonePayload
    | FeedbackRecordedPayload
    | MemoryExtractionStagePayload
    | MemoryCandidateCreatedPayload
    | MemoryAdmissionResolvedPayload
    | MemoryJobFailedPayload
    | MemoryInjectedPayload
    | MemoryUsageVerifiedPayload
    | MemoryUsageFeedbackRecordedPayload
    | MemoryAnalysisStartedPayload
    | MemoryAnalysisCompletedPayload
    | MemoryEffectJudgedPayload
)

PAYLOAD_TYPES: dict[EventType, type[ContractModel]] = {
    EventType.TASK_CREATED: TaskCreatedPayload,
    EventType.TASK_STAGE: TaskStagePayload,
    EventType.TASK_FINGERPRINTED: TaskFingerprintedPayload,
    EventType.MEMORY_RETRIEVAL_STARTED: MemoryRetrievalStartedPayload,
    EventType.MEMORY_RETRIEVAL_COMPLETED: MemoryRetrievalCompletedPayload,
    EventType.AGENT_PLAN_PUBLISHED: AgentPlanPublishedPayload,
    EventType.TOOL_CALLED: ToolCalledPayload,
    EventType.TOOL_RESULT: ToolResultPayload,
    EventType.AGENT_CHUNK: AgentChunkPayload,
    EventType.RUN_METRICS: RunMetricsPayload,
    EventType.RUN_COMPLETED: RunCompletedPayload,
    EventType.RUN_FAILED: RunFailedPayload,
    EventType.ERROR: ErrorPayload,
    EventType.STREAM_DONE: StreamDonePayload,
    EventType.FEEDBACK_RECORDED: FeedbackRecordedPayload,
    EventType.MEMORY_EXTRACTION_STAGE: MemoryExtractionStagePayload,
    EventType.MEMORY_CANDIDATE_CREATED: MemoryCandidateCreatedPayload,
    EventType.MEMORY_ADMISSION_RESOLVED: MemoryAdmissionResolvedPayload,
    EventType.MEMORY_JOB_FAILED: MemoryJobFailedPayload,
    EventType.MEMORY_INJECTED: MemoryInjectedPayload,
    EventType.MEMORY_USAGE_VERIFIED: MemoryUsageVerifiedPayload,
    EventType.MEMORY_USAGE_FEEDBACK_RECORDED: MemoryUsageFeedbackRecordedPayload,
    EventType.MEMORY_ANALYSIS_STARTED: MemoryAnalysisStartedPayload,
    EventType.MEMORY_ANALYSIS_COMPLETED: MemoryAnalysisCompletedPayload,
    EventType.MEMORY_EFFECT_JUDGED: MemoryEffectJudgedPayload,
}


class EventEnvelope(ContractModel):
    event_version: Literal["1.0"] = "1.0"
    event_type: EventType
    event_seq: int | None = Field(default=None, ge=1)
    task_id: TaskId
    run_id: RunId
    at: datetime = Field(default_factory=utc_now)
    data: EventPayload

    @model_validator(mode="after")
    def event_is_correlated(self) -> EventEnvelope:
        expected = PAYLOAD_TYPES[self.event_type]
        if not isinstance(self.data, expected):
            raise ValueError(f"{self.event_type} requires {expected.__name__}")
        if (self.event_type in PERSISTENT_EVENT_TYPES) != (self.event_seq is not None):
            raise ValueError("only persistent events have event_seq")
        if isinstance(self.data, AgentChunkPayload) and self.data.run_id != self.run_id:
            raise ValueError("chunk payload run_id must equal envelope run_id")
        return self


def make_event(
    *,
    event_type: EventType,
    event_seq: int | None,
    task_id: str,
    run_id: str,
    data: ContractModel | dict[str, Any],
) -> EventEnvelope:
    payload = PAYLOAD_TYPES[event_type].model_validate(data)
    return EventEnvelope(
        event_type=event_type,
        event_seq=event_seq,
        task_id=task_id,
        run_id=run_id,
        data=payload,
    )


def serialize_sse(event: EventEnvelope) -> bytes:
    lines: list[str] = []
    if event.event_seq is not None:
        lines.append(f"id: {event.event_seq}")
    lines.append(f"event: {event.event_type.value}")
    lines.append(f"data: {event.model_dump_json()}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")


# Rebuild models that use forward references from schemas.py
EventEnvelope.model_rebuild()
