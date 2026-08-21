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


def utc_now() -> datetime:
    return datetime.now(UTC)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    scenario: Scenario
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


Concept = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]


class TaskFingerprint(ContractModel):
    id: FingerprintId
    schema_version: Literal["1.0"] = "1.0"
    domain: Domain
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

    @field_validator("concepts", "tool_context")
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


class AsyncErrorCode(StrEnum):
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_INPUT_INVALID = "TOOL_INPUT_INVALID"
    STREAM_INTERRUPTED = "STREAM_INTERRUPTED"


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


class TaskSnapshot(ContractModel):
    request_id: RequestId
    task_id: TaskId
    run_id: RunId
    task_status: Literal["active"] = "active"
    run_status: RunStatus
    provider_mode: ProviderMode
    effective_memory_mode: EffectiveMemoryMode
    fingerprint: TaskFingerprint | None = None
    public_plan: PublicPlan | None = None
    tool_decision: ToolDecision | None = None
    tool_calls: Annotated[list[ToolCallSnapshot], Field(max_length=1)]
    partial_output: Annotated[str, StringConstraints(max_length=262_144)] = ""
    end_offset: int = Field(default=0, ge=0, le=262_144)
    offset_unit: Literal["utf8_bytes"] = "utf8_bytes"
    final_message: MessageSnapshot | None = None
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
    data_dir: Literal["pass"] = "pass"
    provider_credentials: Literal["pass", "not_required"]
    provider_network: Literal["unchecked"] = "unchecked"


class ReadyResponse(ContractModel):
    request_id: RequestId
    status: Literal["ready"] = "ready"
    provider_mode: ProviderMode
    checks: ReadinessChecks
    at: datetime


class SseCursorQuery(ContractModel):
    after_event_seq: int = Field(default=0, ge=0)
    after_offset: int = Field(default=0, ge=0, le=262_144)
