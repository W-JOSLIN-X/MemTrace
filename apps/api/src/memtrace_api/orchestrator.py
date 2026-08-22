"""G1 task lifecycle: fingerprint, plan, static tool, streamed answer, and SQLite persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from functools import partial
from typing import Any

from sqlalchemy import and_, update
from sqlalchemy.orm import Session, sessionmaker

from memtrace_api.database import session_scope
from memtrace_api.db_models import (
    AgentRunModel,
    MessageModel,
    TaskFingerprintModel,
    ToolCallModel,
)
from memtrace_api.events import (
    AgentChunkPayload,
    EventType,
    MemoryRetrievalStartedPayload,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.logic import build_public_plan
from memtrace_api.providers import (
    ProviderFailure,
    ProviderRequest,
    ProviderUsage,
    StreamingProvider,
)
from memtrace_api.repositories import TaskRepository, UserContext
from memtrace_api.schemas import (
    AsyncErrorCode,
    MessageRole,
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
        db_session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.tool_registry = tool_registry or ToolRegistry()
        self.db_session_factory = db_session_factory

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

    def _sync_db_event(
        self,
        user_ctx: UserContext,
        task_id: str,
        event_type: EventType,
        metadata: dict[str, Any],
    ) -> int:
        """Allocate next_event_seq and append event_log inside a short sync transaction."""
        if self.db_session_factory is None:
            return 0
        with session_scope(self.db_session_factory) as session:
            task_repo = TaskRepository(user_ctx, session)
            seq = task_repo.allocate_next_event_seq(task_id)
            task_repo.append_event(
                stream_type="task",
                stream_id=task_id,
                seq=seq,
                event_type=event_type.value,
                metadata=metadata,
            )
            return seq

    async def _emit_db_persistent_event(
        self,
        record: TaskRecord,
        event_type: EventType,
        metadata: dict[str, Any],
        *,
        snapshot_updates: dict[str, Any] | None = None,
    ) -> None:
        if record.user_ctx is not None and self.db_session_factory is not None:
            seq = await asyncio.to_thread(
                self._sync_db_event,
                record.user_ctx,
                record.snapshot.task_id,
                event_type,
                metadata,
            )
            await self.store.emit_preallocated_persistent(
                record,
                event_type=event_type,
                event_seq=seq,
                data=metadata,
                snapshot_updates=snapshot_updates,
            )
        else:
            await self.store.emit(
                record,
                event_type,
                metadata,
                snapshot_updates=snapshot_updates,
            )

    async def run(self, record: TaskRecord) -> None:
        measurements = RunMeasurements(started_at=time.perf_counter())
        try:
            await self._stage(
                record,
                RunStatus.FINGERPRINTING,
                "fingerprinting_task",
            )
            analysis = record.analysis

            # Persist fingerprint to DB if factory present
            if record.user_ctx is not None and self.db_session_factory is not None:

                def _save_fp() -> None:
                    with session_scope(self.db_session_factory) as session:
                        fp_model = TaskFingerprintModel(
                            id=analysis.fingerprint.id,
                            owner_id=record.user_ctx.user_id,
                            task_id=record.snapshot.task_id,
                            domain=analysis.fingerprint.domain.value,
                            task_type=analysis.fingerprint.task_type.value,
                            artifact_type=analysis.fingerprint.artifact_type.value,
                            language=analysis.fingerprint.language.value,
                            fingerprint_json=analysis.fingerprint.model_dump_json(),
                            created_at=utc_now(),
                        )
                        session.add(fp_model)

                await asyncio.to_thread(_save_fp)

            fp_payload_dict = {
                "fingerprint_id": analysis.fingerprint.id,
                "domain": analysis.fingerprint.domain.value,
                "classification_source": analysis.fingerprint.classification_source,
                "classification_confidence": analysis.fingerprint.classification_confidence,
                "classification_reasons": [
                    reason.value for reason in analysis.fingerprint.classification_reasons
                ],
                "task_type": analysis.fingerprint.task_type.value,
                "artifact_type": analysis.fingerprint.artifact_type.value,
                "language": analysis.fingerprint.language.value,
            }
            await self._emit_db_persistent_event(
                record,
                EventType.TASK_FINGERPRINTED,
                fp_payload_dict,
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
            plan_payload_dict = {
                "plan_id": plan.id,
                "goal_code": analysis.goal_code,
                "memory_summary_code": "no_long_term_memory_day2",
                "next_action_code": analysis.next_action_code,
            }
            await self._emit_db_persistent_event(
                record,
                EventType.AGENT_PLAN_PUBLISHED,
                plan_payload_dict,
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
                tool_called_dict = {
                    "tool_call_id": tool_call_id,
                    "tool_name": "python_ast_check",
                    "reason_code": "python_code_detected",
                    "args_summary": {
                        "language": "python",
                        "code_source": analysis.extracted_python.source.value,
                        "code_bytes": analysis.extracted_python.byte_count,
                    },
                }
                await self._emit_db_persistent_event(
                    record,
                    EventType.TOOL_CALLED,
                    tool_called_dict,
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

                # Persist tool call in DB
                if record.user_ctx is not None and self.db_session_factory is not None:

                    def _save_tc() -> None:
                        with session_scope(self.db_session_factory) as session:
                            tc_model = ToolCallModel(
                                id=tool_call_id,
                                owner_id=record.user_ctx.user_id,
                                task_id=record.snapshot.task_id,
                                run_id=record.snapshot.run_id,
                                tool_name="python_ast_check",
                                reason=analysis.tool_decision.reason,
                                args_summary_json=json.dumps(
                                    {
                                        "language": "python",
                                        "code_source": analysis.extracted_python.source.value,
                                        "code_bytes": analysis.extracted_python.byte_count,
                                    }
                                ),
                                result_summary_json=completed_call.result.model_dump_json()
                                if completed_call.result
                                else None,
                                status="succeeded",
                                duration_ms=execution.latency_ms,
                                result_ref=result_ref,
                                created_at=utc_now(),
                            )
                            session.add(tc_model)

                    await asyncio.to_thread(_save_tc)

                tool_result_dict = {
                    "tool_call_id": tool_call_id,
                    "tool_name": "python_ast_check",
                    "status": "succeeded",
                    "latency_ms": execution.latency_ms,
                    "result_ref": result_ref,
                }
                await self._emit_db_persistent_event(
                    record,
                    EventType.TOOL_RESULT,
                    tool_result_dict,
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

            # Persist assistant message and run status in DB
            if record.user_ctx is not None and self.db_session_factory is not None:

                def _save_completed() -> None:
                    with session_scope(self.db_session_factory) as session:
                        msg_model = MessageModel(
                            id=message.id,
                            owner_id=record.user_ctx.user_id,
                            task_id=record.snapshot.task_id,
                            run_id=record.snapshot.run_id,
                            role=MessageRole.ASSISTANT.value,
                            content=message.content,
                            created_at=utc_now(),
                        )
                        session.add(msg_model)
                        session.execute(
                            update(AgentRunModel)
                            .where(
                                and_(
                                    AgentRunModel.id == record.snapshot.run_id,
                                    AgentRunModel.owner_id == record.user_ctx.user_id,
                                )
                            )
                            .values(
                                status=RunStatus.SUCCEEDED.value,
                                stage="succeeded",
                                completed_at=utc_now(),
                            )
                        )

                await asyncio.to_thread(_save_completed)

            run_completed_dict = {
                "status": "succeeded",
                "message_id": message.id,
                "end_offset": record.snapshot.end_offset,
                "offset_unit": "utf8_bytes",
            }
            await self._emit_db_persistent_event(
                record,
                EventType.RUN_COMPLETED,
                run_completed_dict,
                snapshot_updates={
                    "run_status": RunStatus.SUCCEEDED,
                    "terminal": True,
                    "final_message": message,
                    "error": None,
                },
            )
            await self._emit_db_persistent_event(
                record,
                EventType.STREAM_DONE,
                {"status": "succeeded", "final_snapshot_required": True},
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
        stage_dict = {"stage": stage.value, "progress_label": progress_label}
        await self._emit_db_persistent_event(
            record,
            EventType.TASK_STAGE,
            stage_dict,
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

        provider_label = _safe_metric_label(self.provider.name, fallback="unknown", limit=64)
        model_label = _safe_metric_label(self.provider.model, fallback="unknown", limit=128)
        total_time_ms = (time.perf_counter() - measurements.started_at) * 1000

        # Update run metrics in DB
        if record.user_ctx is not None and self.db_session_factory is not None:

            def _save_metrics() -> None:
                with session_scope(self.db_session_factory) as session:
                    session.execute(
                        update(AgentRunModel)
                        .where(
                            and_(
                                AgentRunModel.id == record.snapshot.run_id,
                                AgentRunModel.owner_id == record.user_ctx.user_id,
                            )
                        )
                        .values(
                            prompt_tokens=prompt_tokens,
                            output_tokens=output_tokens,
                            token_source=token_source,
                            first_token_ms=measurements.first_token_ms,
                            total_ms=total_time_ms,
                        )
                    )

            await asyncio.to_thread(_save_metrics)

        metrics_dict = {
            "provider": provider_label,
            "model": model_label,
            "provider_mode": self.provider.mode.value,
            "first_token_ms": measurements.first_token_ms,
            "total_ms": total_time_ms,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "token_source": token_source,
        }
        await self._emit_db_persistent_event(
            record,
            EventType.RUN_METRICS,
            metrics_dict,
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

        # Update run status to failed in DB, persisting any partial assistant
        # output so restart recovery returns the accumulated partial_output.
        if record.user_ctx is not None and self.db_session_factory is not None:

            def _save_failed() -> None:
                with session_scope(self.db_session_factory) as session:
                    if record.snapshot.end_offset > 0:
                        session.add(
                            MessageModel(
                                id=new_prefixed_ulid("msg"),
                                owner_id=record.user_ctx.user_id,
                                task_id=record.snapshot.task_id,
                                run_id=record.snapshot.run_id,
                                role=MessageRole.ASSISTANT.value,
                                content=record.snapshot.partial_output,
                                created_at=utc_now(),
                            )
                        )
                    session.execute(
                        update(AgentRunModel)
                        .where(
                            and_(
                                AgentRunModel.id == record.snapshot.run_id,
                                AgentRunModel.owner_id == record.user_ctx.user_id,
                            )
                        )
                        .values(
                            status=RunStatus.FAILED.value,
                            stage="failed",
                            error_code=code.value,
                            completed_at=utc_now(),
                        )
                    )

            await asyncio.to_thread(_save_failed)

        await self._emit_db_persistent_event(
            record,
            EventType.TASK_STAGE,
            {"stage": "failed", "progress_label": "run_failed"},
        )
        error = RunErrorSnapshot(
            error_id=new_prefixed_ulid("err"),
            code=code,
            message=message,
            retryable=retryable,
        )
        partial_message_id = new_prefixed_ulid("msg") if record.snapshot.end_offset > 0 else None
        failed_payload_dict = {
            "status": "failed",
            "error_code": code.value,
            "retryable": retryable,
            "partial_message_id": partial_message_id,
            "end_offset": record.snapshot.end_offset,
            "offset_unit": "utf8_bytes",
        }
        await self._emit_db_persistent_event(
            record,
            EventType.RUN_FAILED,
            failed_payload_dict,
            snapshot_updates={
                "run_status": RunStatus.FAILED,
                "terminal": True,
                "final_message": None,
                "error": error,
            },
        )
        error_payload_dict = {
            "error_id": error.error_id,
            "code": code.value,
            "message": message,
            "retryable": retryable,
        }
        await self._emit_db_persistent_event(
            record,
            EventType.ERROR,
            error_payload_dict,
        )
        await self._emit_db_persistent_event(
            record,
            EventType.STREAM_DONE,
            {"status": "failed", "final_snapshot_required": True},
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
