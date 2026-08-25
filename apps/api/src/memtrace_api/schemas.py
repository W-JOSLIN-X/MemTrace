"""Pydantic models matching the normative G0 REST schema."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

TaskId = Annotated[str, StringConstraints(pattern=r"^task_[0-9A-HJKMNP-TV-Z]{26}$")]
RunId = Annotated[str, StringConstraints(pattern=r"^run_[0-9A-HJKMNP-TV-Z]{26}$")]
RequestId = Annotated[str, StringConstraints(pattern=r"^req_[0-9A-HJKMNP-TV-Z]{26}$")]
MessageId = Annotated[str, StringConstraints(pattern=r"^msg_[0-9A-HJKMNP-TV-Z]{26}$")]
FingerprintId = Annotated[str, StringConstraints(pattern=r"^fp_[0-9A-HJKMNP-TV-Z]{26}$")]
PlanId = Annotated[str, StringConstraints(pattern=r"^plan_[0-9A-HJKMNP-TV-Z]{26}$")]
ToolCallId = Annotated[str, StringConstraints(pattern=r"^tool_[0-9A-HJKMNP-TV-Z]{26}$")]
ToolResultId = Annotated[str, StringConstraints(pattern=r"^toolres_[0-9A-HJKMNP-TV-Z]{26}$")]
ErrorId = Annotated[str, StringConstraints(pattern=r"^err_[0-9A-HJKMNP-TV-Z]{26}$")]
FeedbackId = Annotated[str, StringConstraints(pattern=r"^feedback_[0-9A-HJKMNP-TV-Z]{26}$")]
MemoryJobId = Annotated[str, StringConstraints(pattern=r"^job_[0-9A-HJKMNP-TV-Z]{26}$")]
SessionId = Annotated[str, StringConstraints(pattern=r"^sess_[0-9A-HJKMNP-TV-Z]{26}$")]
UserId = Annotated[str, StringConstraints(pattern=r"^usr_[0-9A-HJKMNP-TV-Z]{26}$")]
IdempotencyKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{8,128}$")]


RelationId = Annotated[str, StringConstraints(pattern=r"^rel_[0-9A-HJKMNP-TV-Z]{26}$")]
ImportBatchId = Annotated[str, StringConstraints(pattern=r"^batch_[0-9A-HJKMNP-TV-Z]{26}$")]
PackId = Annotated[str, StringConstraints(pattern=r"^pack_[0-9A-HJKMNP-TV-Z]{26}$")]
MemoryVersionId = Annotated[str, StringConstraints(pattern=r"^memver_[0-9A-HJKMNP-TV-Z]{26}$")]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _serialize_utc_datetime(value: datetime) -> str:
    """Emit RFC 3339 UTC timestamps even when SQLite returns naive values.

    SQLite does not retain timezone information for ``DateTime(timezone=True)``.
    All persisted timestamps in this service originate from ``utc_now()``, so a
    naive value read back from SQLite is UTC rather than local time.
    """

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_utc_datetimes(self, value: object):
        if isinstance(value, datetime):
            return _serialize_utc_datetime(value)
        return value


class ProviderMode(StrEnum):
    MOCK = "mock"
    REAL = "real"


class EffectiveMemoryMode(StrEnum):
    ON = "on"
    OFF = "off"


class Scenario(StrEnum):
    PROGRAMMING_LEARNING = "programming_learning"
    SOFTWARE_DEVELOPMENT = "software_development"
    GENERAL_TEXT = "general_text"
    OTHER = "other"


class ResponsePolicy(StrEnum):
    DEFAULT = "default"
    GUIDED_HINT = "guided_hint"
    DIRECT_FIX = "direct_fix"


class Urgency(StrEnum):
    NORMAL = "normal"
    URGENT = "urgent"


class CurrentConstraints(ContractModel):
    response_policy: ResponsePolicy
    urgency: Urgency
    memory_disabled: bool
    source: Literal["ui"]


TrimmedTaskText = Annotated[str, StringConstraints(min_length=1, max_length=20_000)]


class TaskCreateRequest(ContractModel):
    task_text: TrimmedTaskText
    memory_mode: EffectiveMemoryMode
    current_constraints: CurrentConstraints

    @field_validator("task_text", mode="before")
    @classmethod
    def trim_task_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        trimmed = value.strip()
        try:
            trimmed.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("task_text must be valid UTF-8") from exc
        return trimmed

    @property
    def effective_memory_mode(self) -> EffectiveMemoryMode:
        if self.memory_mode is EffectiveMemoryMode.OFF or self.current_constraints.memory_disabled:
            return EffectiveMemoryMode.OFF
        return EffectiveMemoryMode.ON


class TaskCreateAccepted(ContractModel):
    request_id: RequestId
    task_id: TaskId
    run_id: RunId
    events_url: Annotated[
        str,
        StringConstraints(pattern=r"^/api/v1/tasks/task_[0-9A-HJKMNP-TV-Z]{26}/events$"),
    ]
    provider_mode: ProviderMode
    effective_memory_mode: EffectiveMemoryMode


class Domain(StrEnum):
    PROGRAMMING_LEARNING = "programming_learning"
    SOFTWARE_DEVELOPMENT = "software_development"
    GENERAL_TEXT = "general_text"
    OTHER = "other"


class TaskType(StrEnum):
    DEBUGGING_GUIDANCE = "debugging_guidance"
    CODE_REVIEW = "code_review"
    CODE_EXPLANATION = "code_explanation"
    CODE_GENERATION = "code_generation"
    ENVIRONMENT_CONFIGURATION = "environment_configuration"
    GENERAL_QUESTION = "general_question"
    OTHER = "other"


class ArtifactType(StrEnum):
    SOURCE_CODE = "source_code"
    CONFIGURATION = "configuration"
    TEXT = "text"
    NONE = "none"
    OTHER = "other"


class ProgrammingLanguage(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    C = "c"
    CPP = "cpp"
    RUST = "rust"
    GO = "go"
    OTHER = "other"
    UNKNOWN = "unknown"


class Audience(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    UNKNOWN = "unknown"


class ClassificationReasonCode(StrEnum):
    CODE_PRESENT = "code_present"
    TECHNICAL_CONTEXT = "technical_context"
    DEBUGGING_CUE = "debugging_cue"
    LEARNING_CUE = "learning_cue"
    EXPLANATION_INTENT = "explanation_intent"
    DEVELOPMENT_ACTION = "development_action"
    DEPLOYMENT_CUE = "deployment_cue"
    TEXT_TASK = "text_task"
    AMBIGUOUS = "ambiguous"


Concept = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]


class TaskFingerprint(ContractModel):
    id: FingerprintId
    schema_version: Literal["1.1"] = "1.1"
    domain: Domain
    classification_source: Literal["auto_rule_v1"] = "auto_rule_v1"
    classification_confidence: float = Field(ge=0, le=1)
    classification_reasons: Annotated[list[ClassificationReasonCode], Field(max_length=5)]
    task_type: TaskType
    artifact_type: ArtifactType
    audience: Audience
    project_key: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None
    language: ProgrammingLanguage
    framework: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None
    concepts: Annotated[list[Concept], Field(max_length=12)]
    tool_context: Annotated[list[Literal["python_ast_check"]], Field(max_length=1)]
    current_constraints: CurrentConstraints
    semantic_query: Annotated[str, StringConstraints(min_length=1, max_length=512)]

    @field_validator("classification_reasons", "concepts", "tool_context")
    @classmethod
    def items_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("list items must be unique")
        return value


class PublicPlan(ContractModel):
    id: PlanId
    goal: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    memory_summary: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    next_action: Annotated[str, StringConstraints(min_length=1, max_length=240)]


class ToolAction(StrEnum):
    CALL = "call"
    SKIP = "skip"


class ToolReasonCode(StrEnum):
    PYTHON_CODE_DETECTED = "python_code_detected"
    NON_PYTHON_TASK = "non_python_task"
    NO_EXTRACTABLE_PYTHON = "no_extractable_python"
    UNSUPPORTED_ARTIFACT = "unsupported_artifact"


class ToolDecision(ContractModel):
    action: ToolAction
    tool_name: Literal["python_ast_check"] | None
    reason_code: ToolReasonCode
    reason: Annotated[str, StringConstraints(min_length=1, max_length=240)]

    @model_validator(mode="after")
    def action_matches_tool(self) -> ToolDecision:
        if self.action is ToolAction.CALL:
            if self.tool_name != "python_ast_check":
                raise ValueError("call decisions require python_ast_check")
            if self.reason_code is not ToolReasonCode.PYTHON_CODE_DETECTED:
                raise ValueError("call decisions require python_code_detected")
        elif self.tool_name is not None or self.reason_code is ToolReasonCode.PYTHON_CODE_DETECTED:
            raise ValueError("skip decisions cannot contain a tool or call reason")
        return self


class CodeSource(StrEnum):
    FENCED_PYTHON = "fenced_python"
    WHOLE_TASK_VALID_PYTHON = "whole_task_valid_python"


class ToolArgsSummary(ContractModel):
    language: Literal["python"] = "python"
    code_source: CodeSource
    code_bytes: int = Field(ge=1, le=102_400)


class AstSyntaxError(ContractModel):
    message: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=1)


class PythonAstResult(ContractModel):
    valid: bool
    syntax_error: AstSyntaxError | None

    @model_validator(mode="after")
    def validity_matches_error(self) -> PythonAstResult:
        if self.valid == (self.syntax_error is not None):
            raise ValueError("valid AST has no syntax_error; invalid AST requires one")
        return self


class ToolCallStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ToolCallSnapshot(ContractModel):
    tool_call_id: ToolCallId
    tool_name: Literal["python_ast_check"] = "python_ast_check"
    reason: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    args_summary: ToolArgsSummary
    status: ToolCallStatus
    latency_ms: float | None = Field(default=None, ge=0)
    result_ref: ToolResultId | None = None
    result: PythonAstResult | None = None

    @model_validator(mode="after")
    def status_matches_result(self) -> ToolCallSnapshot:
        if self.status is ToolCallStatus.RUNNING:
            if (
                self.latency_ms is not None
                or self.result_ref is not None
                or self.result is not None
            ):
                raise ValueError("running tool calls cannot have a result")
        elif self.status is ToolCallStatus.SUCCEEDED:
            if self.latency_ms is None or self.result_ref is None or self.result is None:
                raise ValueError("successful tool calls require latency, result_ref, and result")
        elif self.latency_ms is None or self.result_ref is not None or self.result is not None:
            raise ValueError("failed tool calls require latency and no result")
        return self


class MessageSnapshot(ContractModel):
    id: MessageId
    role: Literal["assistant"] = "assistant"
    content: Annotated[str, StringConstraints(max_length=262_144)]
    created_at: datetime


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class TaskMessageRecord(ContractModel):
    """A persisted message restored via the owner-checked TaskSnapshot.

    Unlike ``MessageSnapshot`` (the terminal ``final_message`` projection), a
    restored message carries its originating ``run_id`` and may be either role.
    """

    message_id: MessageId
    run_id: RunId | None = None
    role: MessageRole
    content: Annotated[str, StringConstraints(max_length=262_144)]
    created_at: datetime


class FeedbackType(StrEnum):
    """Derived feedback category. ``rejected`` is the derived type when the
    client sets ``accepted=false`` without any other signal; ``composite`` is
    used when more than one signal is present."""

    EXPLICIT_TEXT = "explicit_text"
    EDITED_OUTPUT = "edited_output"
    RATING = "rating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPOSITE = "composite"


class FeedbackEventRecord(ContractModel):
    """A persisted feedback event restored via the owner-checked TaskSnapshot.

    Body fields (``explicit_text``/``edited_output``) appear only here, never in
    ``event_log`` metadata.
    """

    feedback_id: FeedbackId
    run_id: RunId
    feedback_type: FeedbackType
    explicit_text: Annotated[str, StringConstraints(min_length=1, max_length=4_000)] | None = None
    edited_output: Annotated[str, StringConstraints(min_length=1, max_length=100_000)] | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    accepted: bool | None = None
    memory_job_id: MemoryJobId
    created_at: datetime


class AsyncErrorCode(StrEnum):
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_INPUT_INVALID = "TOOL_INPUT_INVALID"
    STREAM_INTERRUPTED = "STREAM_INTERRUPTED"
    # Day 2 G1: a run still in a non-terminal stage when the API process
    # restarts is marked failed with this code. It must never be silently
    # resumed or pretend to succeed.
    RUN_INTERRUPTED = "RUN_INTERRUPTED"


class RunErrorSnapshot(ContractModel):
    error_id: ErrorId
    code: AsyncErrorCode
    message: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    retryable: bool


class RunStatus(StrEnum):
    QUEUED = "queued"
    FINGERPRINTING = "fingerprinting"
    RETRIEVING = "retrieving"
    PLANNING = "planning"
    TOOL_RUNNING = "tool_running"
    GENERATING = "generating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DemoAlias(StrEnum):
    BLANK_DEMO = "blank_demo"
    SEEDED_DEMO = "seeded_demo"


class DemoSessionCreateRequest(ContractModel):
    demo_alias: DemoAlias


class DemoSessionResponse(ContractModel):
    request_id: RequestId
    demo_alias: DemoAlias
    expires_at: datetime


class FeedbackCreateRequest(ContractModel):
    explicit_text: Annotated[str, StringConstraints(min_length=1, max_length=4_000)] | None = None
    edited_output: Annotated[str, StringConstraints(min_length=1, max_length=100_000)] | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    accepted: bool | None = None

    @field_validator("explicit_text", "edited_output", mode="before")
    @classmethod
    def check_non_empty_whitespace(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        if not value.strip():
            raise ValueError("feedback text fields must not be empty or whitespace only")
        return value

    @field_validator("rating", mode="before")
    @classmethod
    def strict_integer_rating(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("rating must be a strict integer between 1 and 5")
        return value

    @field_validator("accepted", mode="before")
    @classmethod
    def strict_boolean_accepted(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError("accepted must be a boolean")
        return value

    @model_validator(mode="after")
    def at_least_one_field_present(self) -> FeedbackCreateRequest:
        if (
            self.explicit_text is None
            and self.edited_output is None
            and self.rating is None
            and self.accepted is None
        ):
            raise ValueError("at least one feedback field must be non-null")
        return self


def derive_feedback_type(
    *,
    explicit_text: str | None = None,
    edited_output: str | None = None,
    rating: int | None = None,
    accepted: bool | None = None,
) -> FeedbackType:
    signals = 0
    single_type: FeedbackType | None = None
    if explicit_text is not None:
        signals += 1
        single_type = FeedbackType.EXPLICIT_TEXT
    if edited_output is not None:
        signals += 1
        single_type = FeedbackType.EDITED_OUTPUT
    if rating is not None:
        signals += 1
        single_type = FeedbackType.RATING
    if accepted is not None:
        signals += 1
        single_type = FeedbackType.ACCEPTED if accepted else FeedbackType.REJECTED
    if signals > 1:
        return FeedbackType.COMPOSITE
    if single_type is not None:
        return single_type
    raise ValueError("cannot derive feedback type with no signals")


class FeedbackCreateAccepted(ContractModel):
    request_id: RequestId
    feedback_id: FeedbackId
    memory_job_id: MemoryJobId
    feedback_type: FeedbackType
    job_status: Literal["pending"] = "pending"


class TaskSnapshot(ContractModel):
    request_id: RequestId
    task_id: TaskId
    run_id: RunId
    task_text: TrimmedTaskText
    scenario: Scenario
    task_status: Literal["active"] = "active"
    run_status: RunStatus
    provider_mode: ProviderMode
    effective_memory_mode: EffectiveMemoryMode
    fingerprint: TaskFingerprint | None = None
    public_plan: PublicPlan | None = None
    tool_decision: ToolDecision | None = None
    tool_calls: Annotated[list[ToolCallSnapshot], Field(max_length=1)] = Field(default_factory=list)
    partial_output: Annotated[str, StringConstraints(max_length=262_144)] = ""
    end_offset: int = Field(default=0, ge=0, le=262_144)
    offset_unit: Literal["utf8_bytes"] = "utf8_bytes"
    messages: list[TaskMessageRecord] = Field(default_factory=list)
    final_message: MessageSnapshot | None = None
    feedback_events: list[FeedbackEventRecord] = Field(default_factory=list)
    retrieval_trace: RetrievalTraceResponse | None = None
    memory_usages: list[MemoryUsageResponse] = Field(default_factory=list)
    error: RunErrorSnapshot | None = None
    terminal: bool = False
    last_persistent_event_seq: int = Field(default=0, ge=0)
    updated_at: datetime

    @model_validator(mode="after")
    def state_is_consistent(self) -> TaskSnapshot:
        if len(self.partial_output.encode("utf-8")) != self.end_offset:
            raise ValueError("end_offset must equal the UTF-8 byte length of partial_output")
        if self.run_status is RunStatus.SUCCEEDED:
            if not self.terminal or self.final_message is None or self.error is not None:
                raise ValueError("succeeded snapshots require a final message and no error")
            if self.final_message.content != self.partial_output:
                raise ValueError("final message must equal the accumulated output")
        elif self.run_status is RunStatus.FAILED:
            if not self.terminal or self.error is None or self.final_message is not None:
                raise ValueError("failed snapshots require an error and no final message")
        elif self.terminal or self.final_message is not None or self.error is not None:
            raise ValueError("non-terminal snapshots cannot have final state")
        return self


class HealthResponse(ContractModel):
    request_id: RequestId
    status: Literal["ok"] = "ok"
    service: Literal["memtrace-api"] = "memtrace-api"
    version: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    environment: Literal["development", "test", "production"]
    at: datetime


class ReadinessChecks(ContractModel):
    config: Literal["pass"] = "pass"
    session_secret: Literal["pass"]
    data_dir: Literal["pass"] = "pass"
    provider_credentials: Literal["pass", "not_required"]
    provider_network: Literal["unchecked"] = "unchecked"
    database: Literal["pass"]
    migration_revision: Literal["pass"]


class ReadyResponse(ContractModel):
    request_id: RequestId
    status: Literal["ready"] = "ready"
    provider_mode: ProviderMode
    checks: ReadinessChecks
    at: datetime


class SseCursorQuery(ContractModel):
    after_event_seq: int = Field(default=0, ge=0)
    after_offset: int = Field(default=0, ge=0, le=262_144)


# ======================================================================================
# Day 3 G2: memory admission public contract.
#
# These models are the single source of truth for the G2 REST bodies and the four
# new persistent events. They are frozen here before any implementation so member B
# can build the UI against a stable shape. Nothing here accepts owner_id, domain,
# scenario, memory kind, trust, or status from a request body.
# ======================================================================================

MemoryId = Annotated[str, StringConstraints(pattern=r"^mem_[0-9A-HJKMNP-TV-Z]{26}$")]
MemoryVersionId = Annotated[str, StringConstraints(pattern=r"^memver_[0-9A-HJKMNP-TV-Z]{26}$")]
EvidenceId = Annotated[str, StringConstraints(pattern=r"^evidence_[0-9A-HJKMNP-TV-Z]{26}$")]

TrimmedTitle = Annotated[str, StringConstraints(min_length=4, max_length=40)]
TrimmedRule = Annotated[str, StringConstraints(min_length=20, max_length=300)]


class MemoryKind(StrEnum):
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    PROCEDURE = "procedure"
    EXPERIENCE = "experience"
    ENVIRONMENT = "environment"
    LEARNING_CHECKPOINT = "learning_checkpoint"


class MemoryCardStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"
    PAUSED = "paused"
    SUPERSEDED = "superseded"
    MERGED = "merged"
    ARCHIVED = "archived"
    DELETED = "deleted"


class SourceType(StrEnum):
    EXPLICIT_FEEDBACK = "explicit_feedback"
    EXPLICIT_CORRECTION = "explicit_correction"
    EDIT_DIFF = "edit_diff"
    ACCEPT = "accept"
    REJECT = "reject"
    RATING = "rating"
    OUTCOME = "outcome"
    IMPORT = "import"


class ScopeLevel(StrEnum):
    SESSION = "session"
    TASK_FAMILY = "task_family"
    PROJECT = "project"
    GLOBAL = "global"


class ScopeDomain(StrEnum):
    """Wildcard-aware scope domain. Unlike the auto-detected ``Domain`` (which is
    never ``any``), an explicit ``any`` is the only value that widens a memory's
    applicability across every domain."""

    PROGRAMMING_LEARNING = "programming_learning"
    SOFTWARE_DEVELOPMENT = "software_development"
    GENERAL_TEXT = "general_text"
    OTHER = "other"
    ANY = "any"


class Disposition(StrEnum):
    CANDIDATE_CREATED = "candidate_created"
    EPISODE_ONLY = "episode_only"
    REINFORCE_USAGE_ONLY = "reinforce_usage_only"
    NO_MEMORY = "no_memory"
    FAILED = "failed"


class CandidateResolveAction(StrEnum):
    ACCEPT = "accept"
    EDIT_ACCEPT = "edit_accept"
    REJECT = "reject"
    ONE_SHOT = "one_shot"


class ConflictResolutionAction(StrEnum):
    PREFER = "prefer"
    SEPARATE_SCOPES = "separate_scopes"
    MERGE = "merge"
    PAUSE_BOTH = "pause_both"


# Alias for G4 decision note
ResolutionAction = ConflictResolutionAction


# Alias for backward compatibility
ResolveAction = CandidateResolveAction


class RejectionReason(StrEnum):
    USER_REJECTED = "user_rejected"
    EPISODE_ONLY = "episode_only"


class CreatedByAction(StrEnum):
    ACCEPT = "accept"
    EDIT_ACCEPT = "edit_accept"
    EDIT = "edit"
    IMPORT = "import"
    MERGE = "merge"
    SCOPE_RESOLUTION = "scope_resolution"


class MemoryJobStage(StrEnum):
    """Five observable processing stages plus the three boundary states. The five
    counted stages are diffing, classifying_durability, extracting, validating,
    and admitting; queued/done/failed are boundary states and are not counted."""

    QUEUED = "queued"
    DIFFING = "diffing"
    CLASSIFYING_DURABILITY = "classifying_durability"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    ADMITTING = "admitting"
    DONE = "done"
    FAILED = "failed"


class MemoryJobErrorCode(StrEnum):
    """Controlled job error codes. Provider raw exceptions or bodies are never
    surfaced; only these codes (or ``None``) reach the job response and events."""

    MEMORY_JOB_INTERRUPTED = "MEMORY_JOB_INTERRUPTED"
    MEMORY_JSON_INVALID = "MEMORY_JSON_INVALID"
    MEMORY_SCHEMA_INVALID = "MEMORY_SCHEMA_INVALID"
    MEMORY_REPAIR_FAILED = "MEMORY_REPAIR_FAILED"
    MEMORY_PROVIDER_ERROR = "MEMORY_PROVIDER_ERROR"
    MEMORY_PROVIDER_TIMEOUT = "MEMORY_PROVIDER_TIMEOUT"
    MEMORY_EVIDENCE_NOT_FOUND = "MEMORY_EVIDENCE_NOT_FOUND"
    MEMORY_NO_REUSABLE_CONTENT = "MEMORY_NO_REUSABLE_CONTENT"
    MEMORY_SCOPE_TOO_BROAD = "MEMORY_SCOPE_TOO_BROAD"


class MemoryJobResponse(ContractModel):
    """Frozen G2 job projection. ``disposition`` is ``failed`` only when the whole
    job failed; ``candidate_created`` also appears when no card was produced but
    the run completed cleanly. ``candidate_ids`` is server-derived and ordered."""

    request_id: RequestId
    memory_job_id: MemoryJobId
    feedback_id: FeedbackId
    job_type: Literal["extract_feedback"] = "extract_feedback"
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    stage: MemoryJobStage = MemoryJobStage.QUEUED
    attempt: int = Field(default=0, ge=0)
    candidate_ids: Annotated[list[MemoryId], Field(max_length=3)] = Field(default_factory=list)
    disposition: Disposition | None = None
    error_code: MemoryJobErrorCode | None = None
    retryable: bool = False
    created_at: datetime
    updated_at: datetime


class AllowedException(StrEnum):
    """Controlled, non-executable scope exceptions a card may reference."""

    RESPONSE_POLICY_DIRECT_FIX = "response_policy:direct_fix"
    URGENCY_URGENT = "urgency:urgent"


class MemoryScope(ContractModel):
    level: ScopeLevel
    domain: ScopeDomain
    task_type: TaskType | Literal["any"] | None = None
    artifact_type: ArtifactType | Literal["any"] | None = None
    audience: Audience | Literal["any"] | None = None
    project_key: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    language: ProgrammingLanguage | Literal["any"] | None = None
    framework: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    concepts: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=64)]], Field(max_length=12)
    ] = Field(default_factory=list)

    @field_validator("framework")
    @classmethod
    def normalize_framework(cls, value: str | None) -> str | None:
        if value is None or value == "any":
            return value
        normalized = value.strip().casefold()
        if not normalized or normalized != value:
            raise ValueError("framework must be a normalized lowercase tag or any")
        return normalized

    @field_validator("concepts")
    @classmethod
    def normalized_concepts(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().casefold() for item in value]
        if any(not item for item in normalized):
            raise ValueError("concepts must not contain blank tags")
        return sorted(set(normalized))


class MemoryCard(ContractModel):
    memory_id: MemoryId
    schema_version: Literal["1.0"] = "1.0"
    kind: MemoryKind
    title: TrimmedTitle
    rule: TrimmedRule
    avoid: Annotated[str, StringConstraints(max_length=400)] = ""
    trigger_text: Annotated[str, StringConstraints(max_length=240)] = ""
    scope: MemoryScope
    exceptions: Annotated[list[AllowedException], Field(max_length=8)] = Field(default_factory=list)
    status: MemoryCardStatus
    rejection_reason: RejectionReason | None
    source_type: SourceType
    save_preselected: bool = False
    source_trust: float = Field(ge=0, le=1)
    rule_confidence: float | None = Field(default=None, ge=0, le=1)
    scope_confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_count: int = Field(default=0, ge=0)
    version: int = Field(default=0, ge=0)
    current_version_id: MemoryVersionId | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    retrieved_count: int = Field(default=0, ge=0)
    injected_count: int = Field(default=0, ge=0)
    verified_applied_count: int = Field(default=0, ge=0)
    helpful_count: int = Field(default=0, ge=0)
    harmful_count: int = Field(default=0, ge=0)
    stale_count: int = Field(default=0, ge=0)
    last_used_at: datetime | None = None
    evidence_missing: bool = False
    import_batch_id: ImportBatchId | None = None
    import_source_version: int | None = Field(default=None, ge=1)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def admission_invariants(self) -> MemoryCard:
        if self.status is MemoryCardStatus.CANDIDATE:
            if self.rejection_reason is not None:
                raise ValueError("candidate cards cannot have a rejection reason")
            if self.current_version_id is not None or self.version != 0:
                raise ValueError("candidate cards have version 0 and no current version")
            if self.rule_confidence is not None or self.scope_confidence is not None:
                raise ValueError("candidate cards have null rule/scope confidence")
        if self.status in {MemoryCardStatus.ACTIVE, MemoryCardStatus.PAUSED}:
            if self.rejection_reason is not None:
                raise ValueError("active and paused cards cannot have a rejection reason")
            if self.current_version_id is None or self.version < 1:
                raise ValueError("active and paused cards require a current version")
            if self.rule_confidence is None or self.scope_confidence is None:
                raise ValueError("active and paused cards require confirmed rule/scope confidence")
        if self.status is MemoryCardStatus.REJECTED and self.rejection_reason is None:
            raise ValueError("rejected cards require a rejection reason")
        return self


class MemoryCardPatch(ContractModel):
    title: TrimmedTitle | None = None
    rule: TrimmedRule | None = None
    avoid: Annotated[str, StringConstraints(max_length=400)] | None = None
    trigger_text: Annotated[str, StringConstraints(max_length=240)] | None = None
    scope: MemoryScope | None = None
    exceptions: Annotated[list[AllowedException], Field(max_length=8)] | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> MemoryCardPatch:
        if all(
            value is None
            for value in (
                self.title,
                self.rule,
                self.avoid,
                self.trigger_text,
                self.scope,
                self.exceptions,
            )
        ):
            raise ValueError("edit_accept patch must modify at least one allowed field")
        return self


class ResolveRequest(ContractModel):
    action: ResolveAction
    patch: MemoryCardPatch | None = None

    @model_validator(mode="after")
    def patch_only_for_edit_accept(self) -> ResolveRequest:
        if self.action == ResolveAction.EDIT_ACCEPT:
            if self.patch is None:
                raise ValueError("edit_accept requires a patch")
        elif self.patch is not None:
            raise ValueError("only edit_accept may carry a patch")
        return self


class ResolveResponse(ContractModel):
    request_id: RequestId
    memory_id: MemoryId
    action: ResolveAction
    old_status: MemoryCardStatus
    new_status: MemoryCardStatus
    disposition: Disposition
    memory_version_id: MemoryVersionId | None = None
    card: MemoryCard


class MemoryListResponse(ContractModel):
    request_id: RequestId
    items: Annotated[list[MemoryCard], Field(max_length=100)] = Field(default_factory=list)
    next_cursor: str | None = None


class MemoryEvidenceProjection(ContractModel):
    evidence_id: EvidenceId
    source_type: SourceType
    feedback_id: FeedbackId | None = None
    task_id: TaskId | None = None
    run_id: RunId | None = None
    evidence_quote: Annotated[str, StringConstraints(min_length=1, max_length=2_000)]
    diff_summary: Annotated[str, StringConstraints(min_length=1, max_length=2_000)] | None = None
    normalized_edit_cost: float | None = Field(default=None, ge=0, le=1)
    created_at: datetime


class MemoryVersionProjection(ContractModel):
    memory_version_id: MemoryVersionId
    version: int = Field(ge=1)
    title: TrimmedTitle
    rule: TrimmedRule
    avoid: Annotated[str, StringConstraints(max_length=400)] = ""
    trigger_text: Annotated[str, StringConstraints(max_length=240)] = ""
    scope: MemoryScope
    exceptions: Annotated[list[AllowedException], Field(max_length=8)] = Field(default_factory=list)
    created_by_action: Literal[
        "accept", "edit_accept", "edit", "import", "merge", "scope_resolution"
    ]
    created_at: datetime


class MemoryRelationProjection(ContractModel):
    relation_id: RelationId
    from_memory_id: MemoryId
    to_memory_id: MemoryId
    relation_type: Literal[
        "duplicate_of", "reinforces", "conflicts_with", "supersedes", "merged_into", "related_to"
    ]
    status: Literal["unresolved", "resolved"]
    resolution_action: Literal["prefer", "separate_scopes", "merge", "pause_both"] | None = None
    resolution_memory_id: MemoryId | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class MemoryDetailResponse(ContractModel):
    request_id: RequestId
    card: MemoryCard
    evidence: list[MemoryEvidenceProjection] = Field(default_factory=list)
    versions: list[MemoryVersionProjection] = Field(default_factory=list)
    relations: list[MemoryRelationProjection] = Field(default_factory=list)


# ======================================================================================
# Day 4 G3 retrieval, usage, and memory lifecycle public contract.
# ======================================================================================

RetrievalTraceId = Annotated[str, StringConstraints(pattern=r"^trace_[0-9A-HJKMNP-TV-Z]{26}$")]
UsageId = Annotated[str, StringConstraints(pattern=r"^usage_[0-9A-HJKMNP-TV-Z]{26}$")]
VerificationJobId = Annotated[str, StringConstraints(pattern=r"^vjob_[0-9A-HJKMNP-TV-Z]{26}$")]


class RetrievalMode(StrEnum):
    TFIDF = "tfidf"
    TFIDF_DEGRADED = "tfidf_degraded"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    VIOLATED = "violated"
    NOT_OBSERVABLE = "not_observable"
    UNKNOWN = "unknown"


class UserEffect(StrEnum):
    HELPFUL = "helpful"
    HARMFUL = "harmful"
    STALE = "stale"


class RetrievalReasonCode(StrEnum):
    SELECTED_ABOVE_THRESHOLD = "selected_above_threshold"
    MEMORY_MODE_OFF = "memory_mode_off"
    STATUS_NOT_ACTIVE = "status_not_active"
    NOT_YET_VALID = "not_yet_valid"
    EXPIRED = "expired"
    SCOPE_DOMAIN_MISMATCH = "scope_domain_mismatch"
    SCOPE_TASK_TYPE_MISMATCH = "scope_task_type_mismatch"
    SCOPE_ARTIFACT_MISMATCH = "scope_artifact_mismatch"
    SCOPE_AUDIENCE_MISMATCH = "scope_audience_mismatch"
    SCOPE_PROJECT_MISMATCH = "scope_project_mismatch"
    SCOPE_LANGUAGE_MISMATCH = "scope_language_mismatch"
    SCOPE_FRAMEWORK_MISMATCH = "scope_framework_mismatch"
    CURRENT_CONSTRAINT_OVERRIDE = "current_constraint_override"
    ACTIVE_CONFLICT = "active_conflict"
    INVALID_ACTIVE_CARD = "invalid_active_card"
    EMPTY_VECTOR = "empty_vector"
    BELOW_THRESHOLD = "below_threshold"
    TOP_K_EXCEEDED = "top_k_exceeded"
    PROMPT_BUDGET_EXCEEDED = "prompt_budget_exceeded"


class RetrievalDecisionResponse(ContractModel):
    memory_id: MemoryId
    memory_version_id: MemoryVersionId | None = None
    memory_status: MemoryCardStatus
    retrieved: bool
    selected: bool
    injected: bool
    rank: int | None = Field(default=None, ge=1)
    scope_match: float | None = Field(default=None, ge=0, le=1)
    semantic_similarity: float | None = Field(default=None, ge=0, le=1)
    provenance_confidence: float | None = Field(default=None, ge=0, le=1)
    verified_effect: float | None = Field(default=None, ge=0, le=1)
    recency: float | None = Field(default=None, ge=0, le=1)
    final_score: float | None = Field(default=None, ge=0, le=1)
    reason_codes: list[RetrievalReasonCode] = Field(default_factory=list)


class RetrievalTraceResponse(ContractModel):
    request_id: RequestId
    retrieval_trace_id: RetrievalTraceId
    task_id: TaskId
    run_id: RunId
    retrieval_mode: RetrievalMode
    algorithm_version: Literal["char_tfidf_v1"] = "char_tfidf_v1"
    threshold: float = Field(ge=0, le=1)
    top_k: int = Field(gt=0)
    candidate_count: int = Field(ge=0)
    retrieved_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    injected_count: int = Field(ge=0)
    decisions: list[RetrievalDecisionResponse] = Field(default_factory=list)
    retrieval_ms: int = Field(ge=0)
    memory_chars: int = Field(ge=0)
    memory_tokens_estimated: int = Field(ge=0)
    provider_prompt_tokens_actual: int | None = Field(default=None, ge=0)
    prompt_section_hash: str | None = None
    reason_codes: list[RetrievalReasonCode] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MemoryUsageResponse(ContractModel):
    request_id: RequestId
    usage_id: UsageId
    retrieval_trace_id: RetrievalTraceId
    task_id: TaskId
    run_id: RunId
    memory_id: MemoryId
    memory_version_id: MemoryVersionId
    rank: int = Field(ge=1)
    retrieved: bool
    selected: bool
    injected: bool
    estimated_tokens: int = Field(ge=0)
    verification_status: VerificationStatus
    verification_method: Literal["exact_substring", "structured_provider"] | None = None
    evidence_excerpt: Annotated[str, StringConstraints(max_length=120)] | None = None
    user_effect: UserEffect | None = None
    created_at: datetime
    updated_at: datetime


class ActiveMemoryEditRequest(ContractModel):
    expected_current_version_id: MemoryVersionId
    patch: MemoryCardPatch


class MemoryStateRequest(ContractModel):
    expected_current_version_id: MemoryVersionId


class MemoryUsageFeedbackRequest(ContractModel):
    effect: UserEffect


class MemoryCardListResponse(ContractModel):
    request_id: RequestId
    items: Annotated[list[MemoryCard], Field(max_length=100)] = Field(default_factory=list)
    next_cursor: str | None = None


class MemoryVersionListResponse(ContractModel):
    request_id: RequestId
    items: Annotated[list[MemoryVersionProjection], Field(max_length=100)] = Field(
        default_factory=list
    )
    next_cursor: str | None = None


class MemoryUsageListResponse(ContractModel):
    request_id: RequestId
    items: Annotated[list[MemoryUsageResponse], Field(max_length=100)] = Field(default_factory=list)
    next_cursor: str | None = None


class MemoryListFilter(ContractModel):
    query: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    kind: MemoryKind | None = None
    status: MemoryCardStatus | None = None
    domain: Domain | None = None
    task_type: TaskType | None = None
    source_type: SourceType | None = None
    used_after: datetime | None = None
    sort: Literal["updated_desc", "created_desc", "last_used_desc", "title_asc"] = "updated_desc"
    cursor: str | None = None


class MemoryDeleteRequest(ContractModel):
    expected_current_version_id: MemoryVersionId | None = None
    confirm_title: Annotated[str, StringConstraints(min_length=1, max_length=40)]


class TaskDeleteRequest(ContractModel):
    confirm_task_id: TaskId
    memory_policy: Literal["preserve_and_mark_evidence_missing"] = (
        "preserve_and_mark_evidence_missing"
    )


class MemoryDeleteResponse(ContractModel):
    request_id: RequestId
    memory_id: MemoryId
    status: Literal["deleted"] = "deleted"
    deleted_at: datetime


class TaskDeleteResponse(ContractModel):
    request_id: RequestId
    task_id: TaskId
    status: Literal["deleted"] = "deleted"
    memory_policy: Literal["preserve_and_mark_evidence_missing"]
    affected_card_count: int = Field(ge=0)


class MemoryRelationListResponse(ContractModel):
    request_id: RequestId
    items: Annotated[list[MemoryRelationProjection], Field(max_length=50)] = Field(
        default_factory=list
    )
    next_cursor: str | None = None


class MemoryConflictDetailResponse(ContractModel):
    request_id: RequestId
    relation: MemoryRelationProjection
    left: MemoryCard
    right: MemoryCard


class MergedMemoryCardInput(ContractModel):
    kind: MemoryKind
    title: TrimmedTitle
    rule: TrimmedRule
    avoid: Annotated[str, StringConstraints(max_length=400)] = ""
    trigger_text: Annotated[str, StringConstraints(max_length=240)] = ""
    scope: MemoryScope
    exceptions: Annotated[list[AllowedException], Field(max_length=8)] = Field(default_factory=list)


class MemoryConflictDetectRequest(ContractModel):
    left_memory_id: MemoryId
    left_expected_current_version_id: MemoryVersionId
    right_memory_id: MemoryId
    right_expected_current_version_id: MemoryVersionId


class MemoryConflictDetectResponse(ContractModel):
    request_id: RequestId
    relation_id: RelationId
    left_memory_id: MemoryId
    right_memory_id: MemoryId
    relation_type: Literal["conflicts_with"] = "conflicts_with"
    status: Literal["unresolved"] = "unresolved"


class MemoryConflictResolveRequest(ContractModel):
    expected_relation_status: Literal["unresolved"] = "unresolved"
    left_expected_current_version_id: MemoryVersionId
    right_expected_current_version_id: MemoryVersionId
    action: Literal["prefer", "separate_scopes", "merge", "pause_both"]
    preferred_memory_id: MemoryId | None = None
    left_scope: MemoryScope | None = None
    right_scope: MemoryScope | None = None
    merged_card: MergedMemoryCardInput | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> MemoryConflictResolveRequest:
        present = {
            "preferred_memory_id": self.preferred_memory_id is not None,
            "left_scope": self.left_scope is not None,
            "right_scope": self.right_scope is not None,
            "merged_card": self.merged_card is not None,
        }
        expected = {
            "prefer": {
                "preferred_memory_id": True,
                "left_scope": False,
                "right_scope": False,
                "merged_card": False,
            },
            "separate_scopes": {
                "preferred_memory_id": False,
                "left_scope": True,
                "right_scope": True,
                "merged_card": False,
            },
            "merge": {
                "preferred_memory_id": False,
                "left_scope": False,
                "right_scope": False,
                "merged_card": True,
            },
            "pause_both": {
                "preferred_memory_id": False,
                "left_scope": False,
                "right_scope": False,
                "merged_card": False,
            },
        }[self.action]
        if present != expected:
            raise ValueError(f"{self.action} action fields do not match the frozen contract")
        return self


class MemoryConflictResolveResponse(ContractModel):
    request_id: RequestId
    relation_id: RelationId
    action: Literal["prefer", "separate_scopes", "merge", "pause_both"]
    status: Literal["resolved"] = "resolved"


class MemoryMergeRequest(ContractModel):
    left_memory_id: MemoryId
    left_expected_current_version_id: MemoryVersionId
    right_memory_id: MemoryId
    right_expected_current_version_id: MemoryVersionId
    merged_card: MergedMemoryCardInput


class MemoryMergeResponse(ContractModel):
    request_id: RequestId
    merged_memory_id: MemoryId
    left_memory_id: MemoryId
    right_memory_id: MemoryId


class MemoryVersionDiffResponse(ContractModel):
    request_id: RequestId
    from_version: MemoryVersionProjection
    to_version: MemoryVersionProjection
    changed_fields: list[Literal["title", "rule", "avoid", "trigger_text", "scope", "exceptions"]]


class PackExportRequest(ContractModel):
    memory_ids: Annotated[list[MemoryId], Field(min_length=1, max_length=200)] | None = None
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None
    description: Annotated[str, StringConstraints(max_length=500)] | None = None

    @field_validator("memory_ids")
    @classmethod
    def unique_memory_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("memory_ids must be unique")
        return value


class PackProducer(ContractModel):
    name: Annotated[str, StringConstraints(max_length=80)]
    version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]


class PackSource(ContractModel):
    kind: Literal["user_export", "external_import"]
    trust: Literal["self_asserted", "unverified"]


class PackPrivacy(ContractModel):
    contains_raw_evidence: Literal[False]
    anonymized: Literal[True]


class PackClaimedOrigin(ContractModel):
    source_type: SourceType
    trust_level: Literal["user_confirmed", "self_asserted", "imported_unverified"]
    created_at: datetime
    source_task_exported: bool
    source_version: int = Field(ge=1)


class MemoryPackCard(ContractModel):
    external_id: Annotated[str, StringConstraints(pattern=r"^card_[A-Za-z0-9_-]{1,64}$")]
    schema_version: Literal["1.0"]
    kind: MemoryKind
    title: TrimmedTitle
    rule: TrimmedRule
    avoid: Annotated[str, StringConstraints(max_length=400)]
    trigger_text: Annotated[str, StringConstraints(max_length=240)]
    scope: MemoryScope
    exceptions: Annotated[list[AllowedException], Field(max_length=8)]
    claimed_origin: PackClaimedOrigin
    version: int = Field(ge=1)
    updated_at: datetime


class MemoryPackRelation(ContractModel):
    from_external_id: Annotated[str, StringConstraints(pattern=r"^card_[A-Za-z0-9_-]{1,64}$")]
    to_external_id: Annotated[str, StringConstraints(pattern=r"^card_[A-Za-z0-9_-]{1,64}$")]
    relation_type: Literal[
        "duplicate_of", "reinforces", "conflicts_with", "supersedes", "merged_into"
    ]


class PackIntegrity(ContractModel):
    algorithm: Literal["sha256"]
    canonical_payload_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class MemoryPackDocument(ContractModel):
    schema_ref: Literal["memtrace-memory-pack@1.0.0"]
    format: Literal["memtrace-memory-pack"]
    format_version: Literal["1.0.0"]
    pack_id: PackId
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(max_length=500)]
    created_at: datetime
    producer: PackProducer
    source: PackSource
    privacy: PackPrivacy
    cards: Annotated[list[MemoryPackCard], Field(min_length=1, max_length=200)]
    relations: Annotated[list[MemoryPackRelation], Field(max_length=400)]
    integrity: PackIntegrity


class PackMetadata(ContractModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(max_length=500)]
    format: Literal["memtrace-memory-pack"]
    format_version: Literal["1.0.0"]
    producer: PackProducer
    source: PackSource


class PackExportResponse(ContractModel):
    request_id: RequestId
    pack_id: PackId
    name: str
    description: str | None = None
    created_at: datetime
    producer: dict[str, str]
    card_count: int
    relation_count: int
    canonical_payload_sha256: str


class PackPreviewItem(ContractModel):
    external_id: Annotated[str, StringConstraints(pattern=r"^card_[A-Za-z0-9_-]{1,64}$")]
    kind: MemoryKind
    title: TrimmedTitle
    rule: TrimmedRule
    avoid: Annotated[str, StringConstraints(max_length=400)]
    scope: MemoryScope
    classification: Literal["legal_new", "duplicate", "potential_conflict", "suspicious"]
    reason: (
        Literal[
            "exact_duplicate",
            "declared_conflict",
            "scope_overlap_similarity",
            "suspicious_text",
        ]
        | None
    ) = None


class PackPreviewResponse(ContractModel):
    request_id: RequestId
    batch_id: ImportBatchId
    pack_metadata: PackMetadata
    legal_new_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    potential_conflict_count: int = Field(ge=0)
    suspicious_count: int = Field(ge=0)
    items: Annotated[list[PackPreviewItem], Field(min_length=1, max_length=200)]
    preview_token: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")] | None = None


class ImportCommitRequest(ContractModel):
    batch_id: ImportBatchId
    preview_token: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]
    mode: Literal["import_all_paused"] = "import_all_paused"


class ImportCommitResponse(ContractModel):
    request_id: RequestId
    batch_id: ImportBatchId
    inserted_count: int
    skipped_count: int
    warning_count: int


class ImportBatchResponse(ContractModel):
    request_id: RequestId
    batch_id: ImportBatchId
    status: Literal["quarantined", "committed", "expired", "cancelled"]
    created_at: datetime
    expires_at: datetime | None = None
    inserted_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    error_message: Annotated[str, StringConstraints(max_length=64)] | None = None
