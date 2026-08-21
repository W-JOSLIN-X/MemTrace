"""G0 task lifecycle: fingerprint, plan, static tool, and streamed answer."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from functools import partial

from memtrace_api.events import (
    AgentChunkPayload,
    AgentPlanPublishedPayload,
    ErrorPayload,
    EventType,
    MemoryRetrievalStartedPayload,
    RunCompletedPayload,
    RunFailedPayload,
    RunMetricsPayload,
    SafeToolArgsSummary,
    StreamDonePayload,
    TaskFingerprintedPayload,
    TaskStagePayload,
    ToolCalledPayload,
    ToolResultPayload,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.logic import analyze_task, build_public_plan
from memtrace_api.providers import (
    ProviderFailure,
    ProviderRequest,
    ProviderUsage,
    StreamingProvider,
)
from memtrace_api.schemas import (
    AsyncErrorCode,
    MessageSnapshot,
    ProviderMode,
    RunErrorSnapshot,
    RunStatus,
    ToolAction,
    ToolCallSnapshot,
    ToolCallStatus,
    utc_now,
)
from memtrace_api.store import ReplayCapacityError, TaskRecord, TaskStore
from memtrace_api.tools import ToolFailure, ToolRegistry

MAX_OUTPUT_BYTES = 262_144
MAX_CHUNK_CHARACTERS = 32_768
_SAFE_METRIC_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunMeasurements:
    started_at: float
    first_token_ms: float | None = None
    usage: ProviderUsage | None = None
    metrics_emitted: bool = False


class AgentOrchestrator:
    def __init__(
        self,
        *,
        store: TaskStore,
        provider: StreamingProvider,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.tool_registry = tool_registry or ToolRegistry()

    def start(self, record: TaskRecord) -> asyncio.Task[None]:
        task = asyncio.create_task(
            self.run(record),
            name=f"memtrace-run-{record.snapshot.run_id}",
        )
        record.worker = task
        task.add_done_callback(
            partial(
                _consume_task_exception,
                task_id=record.snapshot.task_id,
                run_id=record.snapshot.run_id,
            )
        )
        return task

    async def run(self, record: TaskRecord) -> None:
        measurements = RunMeasurements(started_at=time.perf_counter())
        try:
            await self._stage(
                record,
                RunStatus.FINGERPRINTING,
                "fingerprinting_task",
            )
            analysis = analyze_task(record.request)
            await self.store.emit(
                record,
                EventType.TASK_FINGERPRINTED,
                TaskFingerprintedPayload(
                    fingerprint_id=analysis.fingerprint.id,
                    domain=analysis.fingerprint.domain,
                    task_type=analysis.fingerprint.task_type,
                    artifact_type=analysis.fingerprint.artifact_type,
                    language=analysis.fingerprint.language,
                ),
                snapshot_updates={"fingerprint": analysis.fingerprint},
            )

            await self._stage(record, RunStatus.RETRIEVING, "retrieving_memory")
            await self.store.emit(
                record,
                EventType.MEMORY_RETRIEVAL_STARTED,
                MemoryRetrievalStartedPayload(),
            )

            await self._stage(record, RunStatus.PLANNING, "publishing_plan")
            plan = build_public_plan(analysis)
            await self.store.emit(
                record,
                EventType.AGENT_PLAN_PUBLISHED,
                AgentPlanPublishedPayload(
                    plan_id=plan.id,
                    goal_code=analysis.goal_code,
                    next_action_code=analysis.next_action_code,
                ),
                snapshot_updates={
                    "public_plan": plan,
                    "tool_decision": analysis.tool_decision,
                },
            )

            tool_result = None
            if analysis.tool_decision.action is ToolAction.CALL:
                if analysis.extracted_python is None:
                    raise ToolFailure(
                        AsyncErrorCode.TOOL_INPUT_INVALID,
                        "Python 工具输入在规划后不可用。",
                    )
                await self._stage(record, RunStatus.TOOL_RUNNING, "running_static_tool")
                tool_call_id = new_prefixed_ulid("tool")
                running_call = ToolCallSnapshot(
                    tool_call_id=tool_call_id,
                    reason=analysis.tool_decision.reason,
                    args_summary=analysis.extracted_python.summary,
                    status=ToolCallStatus.RUNNING,
                )
                await self.store.emit(
                    record,
                    EventType.TOOL_CALLED,
                    ToolCalledPayload(
                        tool_call_id=tool_call_id,
                        args_summary=SafeToolArgsSummary(
                            code_source=analysis.extracted_python.source,
                            code_bytes=analysis.extracted_python.byte_count,
                        ),
                    ),
                    snapshot_updates={"tool_calls": [running_call]},
                )
                execution = self.tool_registry.run(
                    "python_ast_check",
                    analysis.extracted_python,
                )
                tool_result = execution.result
                result_ref = new_prefixed_ulid("toolres")
                completed_call = ToolCallSnapshot(
                    tool_call_id=tool_call_id,
                    reason=analysis.tool_decision.reason,
                    args_summary=analysis.extracted_python.summary,
                    status=ToolCallStatus.SUCCEEDED,
                    latency_ms=execution.latency_ms,
                    result_ref=result_ref,
                    result=execution.result,
                )
                await self.store.emit(
                    record,
                    EventType.TOOL_RESULT,
                    ToolResultPayload(
                        tool_call_id=tool_call_id,
                        status="succeeded",
                        latency_ms=execution.latency_ms,
                        result_ref=result_ref,
                    ),
                    snapshot_updates={"tool_calls": [completed_call]},
                )

            await self._stage(record, RunStatus.GENERATING, "generating_answer")
            await self._stream_answer(
                record,
                ProviderRequest(
                    task_text=record.request.task_text,
                    public_plan=plan,
                    tool_result=tool_result,
                ),
                measurements,
            )
            await self._emit_metrics(record, measurements)

            message = MessageSnapshot(
                id=new_prefixed_ulid("msg"),
                content=record.snapshot.partial_output,
                created_at=utc_now(),
            )
            await self.store.emit(
                record,
                EventType.RUN_COMPLETED,
                RunCompletedPayload(
                    message_id=message.id,
                    end_offset=record.snapshot.end_offset,
                ),
                snapshot_updates={
                    "run_status": RunStatus.SUCCEEDED,
                    "terminal": True,
                    "final_message": message,
                    "error": None,
                },
            )
            await self.store.emit(
                record,
                EventType.STREAM_DONE,
                StreamDonePayload(status="succeeded"),
            )
            await self.store.mark_closed(record)
        except asyncio.CancelledError:
            raise
        except ToolFailure as exc:
            await self._finish_failure(
                record,
                measurements,
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
            )
        except ProviderFailure as exc:
            await self._finish_failure(
                record,
                measurements,
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
            )
        except (ReplayCapacityError, UnicodeError):
            await self._finish_failure(
                record,
                measurements,
                code=AsyncErrorCode.STREAM_INTERRUPTED,
                message="流式结果超过安全容量或包含无效字符。",
                retryable=False,
            )
        except Exception:
            await self._finish_failure(
                record,
                measurements,
                code=AsyncErrorCode.STREAM_INTERRUPTED,
                message="任务运行被意外中断。",
                retryable=False,
            )

    async def _stage(
        self,
        record: TaskRecord,
        stage: RunStatus,
        progress_label: str,
    ) -> None:
        await self.store.emit(
            record,
            EventType.TASK_STAGE,
            TaskStagePayload(stage=stage.value, progress_label=progress_label),
            snapshot_updates={"run_status": stage},
        )

    async def _stream_answer(
        self,
        record: TaskRecord,
        request: ProviderRequest,
        measurements: RunMeasurements,
    ) -> None:
        attempt = 0
        chunk_seq = 0
        emitted_output = False
        while True:
            try:
                async for item in self.provider.stream(request):
                    if item.usage is not None:
                        measurements.usage = item.usage
                    if not item.delta:
                        continue
                    for piece in _split_delta(item.delta):
                        if not emitted_output:
                            measurements.first_token_ms = (
                                time.perf_counter() - measurements.started_at
                            ) * 1000
                        emitted_output = True
                        chunk_seq += 1
                        await self._append_chunk(record, piece, chunk_seq)
                if not emitted_output:
                    raise ProviderFailure(
                        AsyncErrorCode.PROVIDER_ERROR,
                        "模型服务没有返回可展示内容。",
                        retryable=True,
                    )
                return
            except ProviderFailure as exc:
                if not emitted_output and attempt == 0 and exc.retryable:
                    attempt += 1
                    measurements.usage = None
                    continue
                raise

    async def _append_chunk(self, record: TaskRecord, delta: str, chunk_seq: int) -> None:
        try:
            delta_bytes = delta.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ProviderFailure(
                AsyncErrorCode.STREAM_INTERRUPTED,
                "模型流包含无效 Unicode 字符。",
                retryable=False,
            ) from exc
        start_offset = record.snapshot.end_offset
        end_offset = start_offset + len(delta_bytes)
        if end_offset > MAX_OUTPUT_BYTES:
            raise ProviderFailure(
                AsyncErrorCode.STREAM_INTERRUPTED,
                "模型输出超过 256KB 安全上限。",
                retryable=False,
            )
        output = record.snapshot.partial_output + delta
        await self.store.emit(
            record,
            EventType.AGENT_CHUNK,
            AgentChunkPayload(
                run_id=record.snapshot.run_id,
                chunk_seq=chunk_seq,
                start_offset=start_offset,
                end_offset=end_offset,
                delta=delta,
            ),
            snapshot_updates={"partial_output": output, "end_offset": end_offset},
        )

    async def _emit_metrics(
        self,
        record: TaskRecord,
        measurements: RunMeasurements,
    ) -> None:
        if measurements.metrics_emitted:
            return
        usage = measurements.usage
        if usage is None:
            token_source = "unavailable"
            prompt_tokens = None
            output_tokens = None
        else:
            token_source = "mock" if self.provider.mode is ProviderMode.MOCK else "actual"
            prompt_tokens = usage.prompt_tokens
            output_tokens = usage.output_tokens
        await self.store.emit(
            record,
            EventType.RUN_METRICS,
            RunMetricsPayload(
                provider=_safe_metric_label(self.provider.name, fallback="unknown", limit=64),
                model=_safe_metric_label(self.provider.model, fallback="unknown", limit=128),
                provider_mode=self.provider.mode,
                first_token_ms=measurements.first_token_ms,
                total_ms=(time.perf_counter() - measurements.started_at) * 1000,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                token_source=token_source,
            ),
        )
        measurements.metrics_emitted = True

    async def _finish_failure(
        self,
        record: TaskRecord,
        measurements: RunMeasurements,
        *,
        code: AsyncErrorCode,
        message: str,
        retryable: bool,
    ) -> None:
        try:
            await self._emit_metrics(record, measurements)
        except Exception as exc:
            logger.warning(
                "run.metrics_skipped task_id=%s run_id=%s error_type=%s",
                record.snapshot.task_id,
                record.snapshot.run_id,
                type(exc).__name__,
            )
        # The public failed stage must precede run.failed, but TaskSnapshot's
        # failed state is terminal and therefore cannot be published until the
        # structured RunErrorSnapshot exists. Keep the last active snapshot
        # state for this metadata event, then commit the terminal state below.
        await self.store.emit(
            record,
            EventType.TASK_STAGE,
            TaskStagePayload(stage="failed", progress_label="run_failed"),
        )
        error = RunErrorSnapshot(
            error_id=new_prefixed_ulid("err"),
            code=code,
            message=message,
            retryable=retryable,
        )
        partial_message_id = new_prefixed_ulid("msg") if record.snapshot.end_offset > 0 else None
        await self.store.emit(
            record,
            EventType.RUN_FAILED,
            RunFailedPayload(
                error_code=code,
                retryable=retryable,
                partial_message_id=partial_message_id,
                end_offset=record.snapshot.end_offset,
            ),
            snapshot_updates={
                "run_status": RunStatus.FAILED,
                "terminal": True,
                "final_message": None,
                "error": error,
            },
        )
        await self.store.emit(
            record,
            EventType.ERROR,
            ErrorPayload(
                error_id=error.error_id,
                code=code,
                message=message,
                retryable=retryable,
            ),
        )
        await self.store.emit(
            record,
            EventType.STREAM_DONE,
            StreamDonePayload(status="failed"),
        )
        await self.store.mark_closed(record)


def _split_delta(delta: str) -> list[str]:
    return [
        delta[index : index + MAX_CHUNK_CHARACTERS]
        for index in range(0, len(delta), MAX_CHUNK_CHARACTERS)
        if delta[index : index + MAX_CHUNK_CHARACTERS]
    ]


def _safe_metric_label(value: object, *, fallback: str, limit: int) -> str:
    if not isinstance(value, str):
        return fallback
    candidate = value.strip()
    if not candidate or len(candidate) > limit or _SAFE_METRIC_LABEL.fullmatch(candidate) is None:
        return fallback
    return candidate


def _consume_task_exception(
    task: asyncio.Task[None],
    *,
    task_id: str,
    run_id: str,
) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "run.unhandled_exception task_id=%s run_id=%s error_type=%s",
            task_id,
            run_id,
            type(exc).__name__,
        )
