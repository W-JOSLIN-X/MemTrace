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
    MemoryCardModel,
    MessageModel,
    TaskFingerprintModel,
    ToolCallModel,
)
from memtrace_api.events import (
    AgentChunkPayload,
    EventType,
    MemoryRetrievalStartedPayload,
)
from memtrace_api.g3_service import (
    RetrievalExecution,
    execute_and_persist_retrieval,
    mark_injected_unknown,
    update_actual_prompt_tokens,
    verify_injected_usages,
)
from memtrace_api.judges import ApplicabilityJudge, EffectJudge
from memtrace_api.providers import (
    ProviderFailure,
    ProviderRequest,
    ProviderUsage,
    StreamingProvider,
)
from memtrace_api.repositories import TaskRepository, UserContext
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.schemas import (
    AsyncErrorCode,
    MessageRole,
    MessageSnapshot,
    ProviderMode,
    PublicPlan,
    RunErrorSnapshot,
    RunStatus,
    ToolAction,
    ToolCallSnapshot,
    ToolCallStatus,
    utc_now,
)
from memtrace_api.store import ReplayCapacityError, TaskRecord, TaskStore
from memtrace_api.retrieval_executor import CONTEXT_OPEN, CONTEXT_CLOSE
from memtrace_api.tools import ToolFailure, ToolRegistry
from memtrace_api.verifier import verify_exact_substring

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
        memory_reflection_worker: Any | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.tool_registry = tool_registry or ToolRegistry()
        self.db_session_factory = db_session_factory
        self._memory_reflection_worker = memory_reflection_worker
        # v2: LLM judges are instantiated lazily on first use to avoid
        # creating a second Settings() at init time.
        self._applicability_judge: ApplicabilityJudge | None = None
        self._effect_judge: EffectJudge | None = None

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

            # Persist fingerprint to DB if factory present.
            # v2: domain/task_type/artifact_type/language are legacy
            # compatibility fields only — they no longer drive memory
            # injection or the main product flow.
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

            # v2: domain/task_type are legacy fields kept for backward
            # compatibility and debugging only. They are NOT used for
            # memory retrieval, injection decisions, or product flow.
            # auto_rule_v1 keyword classification has been removed from
            # the product semantic chain.
            fp_payload_dict = {
                "fingerprint_id": analysis.fingerprint.id,
                # classification_source retained for event schema compat;
                # v2: values are neutral, this field no longer drives product flow
                "classification_source": "auto_rule_v1",
                "classification_confidence": analysis.fingerprint.classification_confidence,
                "classification_reasons": [
                    reason.value for reason in analysis.fingerprint.classification_reasons
                ],
                "domain": analysis.fingerprint.domain.value,
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

            retrieval: RetrievalExecution | None = None
            applicable_usages: list[dict[str, Any]] = []
            if record.user_ctx is not None and self.db_session_factory is not None:

                def _retrieve() -> RetrievalExecution:
                    with session_scope(self.db_session_factory) as session:
                        return execute_and_persist_retrieval(
                            session,
                            record.user_ctx,
                            request_id=record.snapshot.request_id,
                            task_id=record.snapshot.task_id,
                            run_id=record.snapshot.run_id,
                            fingerprint=analysis.fingerprint,
                            effective_memory_mode=record.request.effective_memory_mode.value,
                        )

                retrieval = await asyncio.to_thread(_retrieve)

                # v2: Run LLM Applicability Judge on selected candidates.
                # This replaces char_tfidf_v1 as the final semantic decision.
                # Judge failure → "irrelevant", never fallback to TF-IDF score.
                if (
                    retrieval is not None
                    and retrieval.trace.selected_count > 0
                    and self._applicability_judge is not None
                ):
                    applicable_usages = await self._run_applicability_judge(
                        record, retrieval
                    )

                for index, event in enumerate(retrieval.events):
                    await self.store.emit_preallocated_persistent(
                        record,
                        event_type=event.event_type,
                        event_seq=event.event_seq,
                        data=event.data,
                        snapshot_updates=(
                            {
                                "retrieval_trace": retrieval.trace,
                                "memory_usages": retrieval.usages,
                            }
                            if index == 0
                            else None
                        ),
                    )

            await self._stage(record, RunStatus.PLANNING, "publishing_plan")
            # v2: plan is now a simple metadata dict, not built by auto_rule_v1
            _goal = "analyze_code"
            _memory_summary = (
                "memory_selected"
                if retrieval is not None and retrieval.trace.selected_count
                else "no_memory_selected"
            )
            _next_action = "python_ast_check" if analysis.tool_decision.action is ToolAction.CALL else "generate_directly"
            plan = PublicPlan(
                id=new_prefixed_ulid("plan"),
                goal=_goal,
                memory_summary=_memory_summary,
                next_action=_next_action,
            )
            plan_payload_dict = {
                "plan_id": plan.id,
                "goal_code": plan.goal,
                "memory_summary_code": plan.memory_summary,
                "next_action_code": plan.next_action,
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
            # v2: Only inject memories that passed the LLM applicability judge.
            # Judge failure → empty context, never fallback to TF-IDF injection.
            applicable_context = None
            applicable_usage_ids = ()
            if applicable_usages and retrieval is not None:
                # Build a map of usage_id → memory_id for the applicable ones
                applicable_mem_ids = {u["memory_id"] for u in applicable_usages}
                applicable_usage_ids = tuple(u["usage_id"] for u in applicable_usages)
                # Rebuild memory_context with only applicable memories
                applicable_context = self._build_applicable_context(
                    retrieval, applicable_mem_ids
                )

            await self._stream_answer(
                record,
                ProviderRequest(
                    task_text=record.request.task_text,
                    public_plan=plan,
                    tool_result=tool_result,
                    memory_context=applicable_context,
                    usage_ids=applicable_usage_ids,
                ),
                measurements,
            )

            # v2: Run LLM Effect Judge on applicable memories after answer
            effect_results: list[dict[str, Any]] = []
            if applicable_usages and self._effect_judge is not None:
                effect_results = await self._run_effect_judge(
                    record, applicable_usages, record.snapshot.partial_output
                )
            await self._emit_metrics(record, measurements)

            message = MessageSnapshot(
                id=new_prefixed_ulid("msg"),
                content=record.snapshot.partial_output,
                created_at=utc_now(),
            )

            # Persist assistant message and run status in DB
            if record.user_ctx is not None and self.db_session_factory is not None:

                def _save_completed():
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

                        update_actual_prompt_tokens(
                            session,
                            record.user_ctx,
                            run_id=record.snapshot.run_id,
                            prompt_tokens=(
                                measurements.usage.prompt_tokens
                                if self.provider.mode is ProviderMode.REAL
                                and measurements.usage is not None
                                else None
                            ),
                        )
                        return verify_injected_usages(
                            session,
                            record.user_ctx,
                            request_id=record.snapshot.request_id,
                            task_id=record.snapshot.task_id,
                            run_id=record.snapshot.run_id,
                            output=message.content,
                        )

                verified_usages, verified_events = await asyncio.to_thread(_save_completed)
                for index, event in enumerate(verified_events):
                    await self.store.emit_preallocated_persistent(
                        record,
                        event_type=event.event_type,
                        event_seq=event.event_seq,
                        data=event.data,
                        snapshot_updates=(
                            {"memory_usages": verified_usages} if index == 0 else None
                        ),
                    )

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
            # Fire reflection job as a separate event (not on STREAM_DONE payload
            # which is schema-validated against StreamDonePayload).
            await self._enqueue_reflection_job(
                record, self.provider.model or "unknown"
            )
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
        except Exception as exc:
            logger.exception("task.run_unexpected type=%s", type(exc).__name__)
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
                    mark_injected_unknown(
                        session,
                        record.user_ctx,
                        run_id=record.snapshot.run_id,
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

    async def _run_applicability_judge(
        self, record: TaskRecord, retrieval: RetrievalExecution
    ) -> list[dict[str, Any]]:
        """Run LLM Applicability Judge on selected memories.

        Returns list of dicts with usage_id/memory_id for applicable memories.
        Judge failure → memory is NOT injected (safe default: irrelevant).
        """
        if self._applicability_judge is None:
            return []
        task_text = record.request.task_text
        constraints = record.request.current_constraints
        constraint_str = json.dumps(constraints.model_dump() if hasattr(constraints, "model_dump") else constraints)

        applicable: list[dict[str, Any]] = []
        usage_map = {u.memory_id: u for u in retrieval.usages}

        # Build nearby context from already-selected memories
        nearby = [
            {
                "id": decision.memory_id,
                "kind": "",  # Not needed for applicability, but available
                "content": "",
                "applies_when": "",
            }
            for decision in retrieval.trace.decisions
            if decision.selected and decision.memory_id != usage_map.keys()
        ][:3]

        for decision in retrieval.trace.decisions:
            if not decision.selected:
                continue
            card = None
            version_content = ""
            version_applies = ""
            # We need to look up card details — fetch from DB
            if record.user_ctx is not None and self.db_session_factory is not None:
                def _get_card(d_mid):
                    with session_scope(self.db_session_factory) as session:
                        return session.get(
                            MemoryCardModel, d_mid
                        ) if hasattr(MemoryCardModel, 'id') else None
                card_row = await asyncio.to_thread(
                    _get_card, decision.memory_id
                )
                if card_row is not None:
                    version_content = card_row.content or ""
                    version_applies = card_row.applies_when or ""

            candidate = {
                "id": decision.memory_id,
                "kind": "unknown",
                "content": version_content,
                "applies_when": version_applies,
            }

            try:
                result = await self._applicability_judge.judge(
                    task_text=task_text,
                    constraints=constraint_str,
                    candidate_memory=candidate,
                    nearby_memories=nearby,
                )
            except Exception as exc:
                logger.warning(
                    "applicability_judge_error memory_id=%s error=%s",
                    decision.memory_id, exc,
                )
                # Judge unavailable → do not inject (safe default)
                continue

            if result.applicability.value == "applicable":
                usage = usage_map.get(decision.memory_id)
                if usage is not None:
                    applicable.append({
                        "usage_id": usage.usage_id,
                        "memory_id": decision.memory_id,
                        "judgment": result.applicability.value,
                        "confidence": result.confidence,
                        "reason_code": result.reason_code.value,
                    })
            # "current_instruction_override" and "conflict" → explicitly excluded
            # "irrelevant" → naturally excluded

        return applicable

    def _build_applicable_context(
        self,
        retrieval: RetrievalExecution,
        applicable_mem_ids: set[str],
    ) -> str | None:
        """Rebuild memory_context from only applicable memory blocks."""
        if not retrieval.memory_context:
            return None
        # Parse the XML blocks and filter
        import re
        block_pattern = re.compile(
            r'<MEMORY[^>]*>.*?</MEMORY>',
            re.DOTALL,
        )
        id_pattern = re.compile(r'id="([^"]+)"')
        applicable_blocks = []
        for block in block_pattern.finditer(retrieval.memory_context):
            block_text = block.group()
            id_match = id_pattern.search(block_text)
            if id_match and id_match.group(1) in applicable_mem_ids:
                applicable_blocks.append(block_text)
        if not applicable_blocks:
            return None
        return (
            f'{CONTEXT_OPEN}\n'
            + "\n".join(applicable_blocks)
            + f"\n{CONTEXT_CLOSE}"
        )

    async def _run_effect_judge(
        self,
        record: TaskRecord,
        applicable_usages: list[dict[str, Any]],
        answer_text: str,
    ) -> list[dict[str, Any]]:
        """Run LLM Effect Judge after answer generation.

        Judge failure → "unknown", never fallback to substring verifier.
        """
        if self._effect_judge is None or not applicable_usages:
            return []

        # Need card content for effect judge — fetch from DB
        task_text = record.request.task_text
        results: list[dict[str, Any]] = []

        if record.user_ctx is not None and self.db_session_factory is not None:
            def _fetch_cards():
                with session_scope(self.db_session_factory) as session:
                    return {
                        row.id: (row.content or "", row.applies_when or "")
                        for row in session.execute(
                            select(MemoryCardModel.id, MemoryCardModel.content, MemoryCardModel.applies_when)
                            .where(
                                and_(
                                    MemoryCardModel.id.in_(
                                        [u["memory_id"] for u in applicable_usages]
                                    ),
                                    MemoryCardModel.owner_id == record.user_ctx.user_id,
                                )
                            )
                        ).tuples().all()
                    }
            cards_data = await asyncio.to_thread(_fetch_cards)
        else:
            cards_data = {}

        for usage_info in applicable_usages:
            mem_id = usage_info["memory_id"]
            content, applies_when = cards_data.get(mem_id, ("", ""))

            try:
                result = await self._effect_judge.judge(
                    task_text=task_text,
                    memory_content=content,
                    answer_text=answer_text,
                )
            except Exception as exc:
                logger.warning(
                    "effect_judge_error memory_id=%s error=%s", mem_id, exc
                )
                result = None

            entry = {
                "usage_id": usage_info["usage_id"],
                "memory_id": mem_id,
                "judgment": result.judgment.value if result else "unknown",
                "confidence": result.confidence if result else 0.0,
                "reason_code": result.reason_code.value if result else "judge_unavailable",
                "excerpt": result.evidence_excerpt if result else "",
            }
            results.append(entry)

        return results

    async def _enqueue_reflection_job(
        self, record: TaskRecord, provider_model: str
    ) -> str | None:
        """Enqueue a memory reflection job after task completion.

        Returns the job_id if enqueued, None otherwise.
        """
        if self._memory_reflection_worker is None:
            return None
        if record.user_ctx is None:
            return None
        if record.snapshot.effective_memory_mode == "off":
            return None
        if not record.snapshot.partial_output:
            return None

        try:
            job_id = new_prefixed_ulid("memjob")
            turn_index = record.snapshot.messages.__len__()
            self._memory_reflection_worker.enqueue_job(
                job_id=job_id,
                owner_id=record.user_ctx.user_id,
                task_id=record.snapshot.task_id,
                run_id=record.snapshot.run_id,
                turn_index=turn_index,
                provider_model=provider_model,
            )
            logger.info(
                "orchestrator.enqueue job_id=%s task_id=%s run_id=%s",
                job_id,
                record.snapshot.task_id,
                record.snapshot.run_id,
            )
            return job_id
        except Exception as exc:
            logger.warning(
                "orchestrator.enqueue_failed type=%s error=%s",
                type(exc).__name__,
                exc,
            )
            return None


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
