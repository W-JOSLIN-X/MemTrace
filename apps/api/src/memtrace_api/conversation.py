"""Conversation-first G5 orchestration with LLM-only semantic decisions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.orm import Session

from memtrace_api.config import Settings
from memtrace_api.conversation_stream import ConversationStreamHub
from memtrace_api.database import session_scope
from memtrace_api.db_models import (
    AgentRunModel,
    EventLogModel,
    MemoryCardModel,
    MemoryEventCursorModel,
    MemoryLLMJudgeModel,
    MemoryReflectionJobModel,
    MemoryUsageModel,
    MemoryVersionModel,
    MessageModel,
    RetrievalDecisionModel,
    RetrievalTraceModel,
    TaskModel,
    ToolCallModel,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.judges import ApplicabilityJudge, EffectJudge, JudgeCall
from memtrace_api.memory_worker import MemoryReflectionWorker
from memtrace_api.providers import (
    FunctionCallOutput,
    ProviderFailure,
    ProviderMessage,
    ProviderRequest,
    ProviderStreamItem,
    StreamingProvider,
    StructuredOutput,
    StructuredProvider,
)
from memtrace_api.repositories import UserContext
from memtrace_api.retrieval_executor import (
    CONTEXT_CLOSE,
    CONTEXT_OPEN,
    escape_xml,
    estimate_tokens,
)
from memtrace_api.schemas import (
    ApplicabilityJudgeResult,
    ApplicabilityResult,
    AsyncErrorCode,
    ConversationMessageProjection,
    ConversationTaskSnapshotResponse,
    ConversationTurnResponse,
    ConversationTurnStateProjection,
    EffectiveMemoryMode,
    EffectJudgeResult,
    MemoryReflectionJobId,
    MessageRole,
    ProviderMode,
    PythonAstResult,
    ReviewStatus,
    RollingSummaryWireResult,
    StageUsageProjection,
    ToolArgsSummary,
    ToolCallSnapshot,
    ToolCallStatus,
    TurnMemoryDecisionProjection,
    utc_now,
)
from memtrace_api.tools import (
    ExtractedPython,
    ToolExecution,
    ToolFailure,
    ToolRegistry,
    extract_python_candidates,
)

_SAFE_FTS_TOKEN = re.compile(r"[\w\-]{2,}", re.UNICODE)


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    card: MemoryCardModel
    version: MemoryVersionModel

    def semantic_data(self) -> dict[str, object]:
        return {
            "memory_id": self.card.id,
            "kind": self.card.memory_kind_v2,
            "content": self.card.content,
            "applies_when": self.card.applies_when,
            "current_version_id": self.card.current_version_id,
        }


@dataclass(frozen=True, slots=True)
class ApplicabilityCall:
    candidate: MemoryCandidate
    call: JudgeCall[ApplicabilityJudgeResult]


@dataclass(frozen=True, slots=True)
class CompiledMemory:
    candidate: MemoryCandidate
    judgment: ApplicabilityJudgeResult
    block: str
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class ChatCall:
    answer: str
    final: ProviderStreamItem


@dataclass(frozen=True, slots=True)
class SummaryCall:
    summary: str
    through_turn_index: int
    provider: StructuredOutput


@dataclass(frozen=True, slots=True)
class ToolPlanningCall:
    provider: FunctionCallOutput
    candidate: ExtractedPython | None
    execution: ToolExecution | None
    tool_call_id: str | None
    result_ref: str | None


class ConversationBusyError(RuntimeError):
    """A task already has a live G5 turn and must remain sequential."""


class ConversationService:
    def __init__(
        self,
        *,
        session_factory,
        settings: Settings,
        chat_provider: StreamingProvider,
        semantic_provider: StructuredProvider,
        reflection_worker: MemoryReflectionWorker | None,
        stream_hub: ConversationStreamHub | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._chat_provider = chat_provider
        self._semantic_provider = semantic_provider
        self._reflection_worker = reflection_worker
        self._stream_hub = stream_hub
        self._tools = ToolRegistry()
        self._applicability = ApplicabilityJudge(provider=semantic_provider)
        self._effect = EffectJudge(provider=semantic_provider)

    def create_task(
        self,
        user_ctx: UserContext,
        *,
        memory_mode: EffectiveMemoryMode,
    ) -> TaskModel:
        now = utc_now()
        task = TaskModel(
            id=new_prefixed_ulid("task"),
            owner_id=user_ctx.user_id,
            scenario="other",
            task_text="",
            effective_memory_mode=memory_mode.value,
            status="active",
            next_event_seq=1,
            conversation_summary=None,
            summary_through_turn=0,
            next_turn_index=1,
            created_at=now,
            updated_at=now,
        )
        with session_scope(self._session_factory) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            session.add(task)
            session.flush([task])
            session.expunge(task)
        return task

    async def run_turn(
        self,
        user_ctx: UserContext,
        *,
        request_id: str,
        task_id: str,
        content: str,
        memory_mode: EffectiveMemoryMode | None,
    ) -> ConversationTurnResponse:
        run_id = new_prefixed_ulid("run")
        user_message_id = new_prefixed_ulid("msg")
        turn_index, effective_mode, started_event_seq = self._begin_turn(
            user_ctx,
            task_id=task_id,
            run_id=run_id,
            user_message_id=user_message_id,
            content=content,
            memory_mode=memory_mode,
        )
        await self._publish_state(
            user_ctx,
            task_id=task_id,
            event_type="turn.started",
            event_seq=started_event_seq,
            metadata={
                "run_id": run_id,
                "turn_index": turn_index,
                "user_message_id": user_message_id,
            },
        )
        try:
            history_rows, candidates, existing_summary = self._load_context(
                user_ctx,
                task_id=task_id,
                current_turn=content,
                memory_mode=effective_mode,
            )
            history, conversation_summary, summary_call = await self._prepare_history(
                user_ctx,
                task_id=task_id,
                run_id=run_id,
                history_rows=history_rows,
                existing_summary=existing_summary,
            )
            applicability_calls = await self._judge_applicability(
                current_turn=content,
                candidates=candidates,
            )
            compiled = _compile_memories(
                applicability_calls,
                per_card_budget=self._settings.memory_token_budget_per_card,
                total_budget=self._settings.memory_token_budget_total,
                top_k=self._settings.memory_top_k,
            )
            usage_ids, trace_id = self._persist_retrieval(
                user_ctx,
                request_id=request_id,
                task_id=task_id,
                run_id=run_id,
                candidates=candidates,
                calls=applicability_calls,
                compiled=compiled,
                memory_mode=effective_mode,
            )
            memory_context = _compile_section(compiled)
            tool_plan = await self._plan_tool(
                content=content,
                history=history,
                conversation_summary=conversation_summary,
            )
            tool_projection: ToolCallSnapshot | None = None
            if tool_plan is not None:
                tool_projection, tool_event_seq = self._persist_tool_plan(
                    user_ctx,
                    task_id=task_id,
                    run_id=run_id,
                    turn_index=turn_index,
                    plan=tool_plan,
                )
                await self._publish_state(
                    user_ctx,
                    task_id=task_id,
                    event_type=(
                        "conversation.tool.completed"
                        if tool_projection is not None
                        else "conversation.tool.skipped"
                    ),
                    event_seq=tool_event_seq,
                    metadata=_tool_event_metadata(
                        run_id=run_id,
                        turn_index=turn_index,
                        plan=tool_plan,
                    ),
                )
            chat = await self._chat(
                user_ctx=user_ctx,
                task_id=task_id,
                run_id=run_id,
                content=content,
                history=history,
                conversation_summary=conversation_summary,
                memory_context=memory_context,
                usage_ids=usage_ids,
                tool_result=(
                    tool_plan.execution.result
                    if tool_plan is not None and tool_plan.execution is not None
                    else None
                ),
            )
            effects = await self._judge_effects(
                current_turn=content,
                compiled=compiled,
                answer=chat.answer,
            )
            assistant_message_id = new_prefixed_ulid("msg")
            reflection_job_id = (
                new_prefixed_ulid("job")
                if self._reflection_worker is not None and effective_mode is EffectiveMemoryMode.ON
                else None
            )
            user_message, assistant_message, decisions, completed_event_seq = self._commit_turn(
                user_ctx,
                task_id=task_id,
                run_id=run_id,
                trace_id=trace_id,
                turn_index=turn_index,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                answer=chat.answer,
                chat=chat,
                compiled=compiled,
                applicability_calls=applicability_calls,
                effects=effects,
                reflection_job_id=reflection_job_id,
            )
            await self._publish_state(
                user_ctx,
                task_id=task_id,
                event_type="turn.completed",
                event_seq=completed_event_seq,
                metadata={
                    "run_id": run_id,
                    "turn_index": turn_index,
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id,
                    "reflection_pending": reflection_job_id is not None,
                    "job_id": reflection_job_id,
                },
            )
            if reflection_job_id is not None and self._reflection_worker is not None:
                self._reflection_worker.notify()
            usage = [
                *(
                    [_stage_usage("summary", summary_call.provider, self._semantic_provider)]
                    if summary_call is not None
                    else []
                ),
                *(
                    _stage_usage("applicability", item.call.provider, self._semantic_provider)
                    for item in applicability_calls
                ),
                *(
                    [_stage_usage_from_function(tool_plan.provider, self._chat_provider)]
                    if tool_plan is not None
                    else []
                ),
                _stage_usage_from_stream(chat.final, self._chat_provider),
                *(
                    _stage_usage("effect", call.provider, self._semantic_provider)
                    for _, call in effects
                ),
            ]
            return ConversationTurnResponse(
                request_id=request_id,
                task_id=task_id,
                run_id=run_id,
                turn_index=turn_index,
                user_message=user_message,
                assistant_message=assistant_message,
                reflection_job_id=reflection_job_id,
                memory_mode=effective_mode,
                memory_decisions=decisions,
                tool_calls=[tool_projection] if tool_projection is not None else [],
                usage=usage,
            )
        except Exception as exc:
            error_code = (
                exc.code.value
                if isinstance(exc, (ProviderFailure, ToolFailure))
                else "PROVIDER_ERROR"
            )
            failed_event_seq = self._fail_run(
                user_ctx,
                task_id=task_id,
                run_id=run_id,
                error_code=error_code,
            )
            if failed_event_seq is not None:
                await self._publish_state(
                    user_ctx,
                    task_id=task_id,
                    event_type="turn.failed",
                    event_seq=failed_event_seq,
                    metadata={
                        "run_id": run_id,
                        "turn_index": turn_index,
                        "error_code": error_code,
                    },
                )
            raise

    async def _publish_state(
        self,
        user_ctx: UserContext,
        *,
        task_id: str,
        event_type: str,
        event_seq: int,
        metadata: dict[str, object],
    ) -> None:
        if self._stream_hub is None:
            return
        await self._stream_hub.publish_state(
            owner_id=user_ctx.user_id,
            task_id=task_id,
            event_type=event_type,
            event_seq=event_seq,
            metadata=metadata,
        )

    def snapshot(
        self,
        user_ctx: UserContext,
        *,
        request_id: str,
        task_id: str,
    ) -> ConversationTaskSnapshotResponse | None:
        with session_scope(self._session_factory) as session:
            task = session.execute(
                select(TaskModel).where(
                    and_(
                        TaskModel.id == task_id,
                        TaskModel.owner_id == user_ctx.user_id,
                        TaskModel.status != "deleted",
                    )
                )
            ).scalar_one_or_none()
            if task is None:
                return None
            messages = list(
                session.execute(
                    select(MessageModel)
                    .where(
                        and_(
                            MessageModel.task_id == task_id,
                            MessageModel.owner_id == user_ctx.user_id,
                            MessageModel.turn_index.is_not(None),
                        )
                    )
                    .order_by(
                        MessageModel.turn_index.asc(),
                        MessageModel.created_at.asc(),
                        MessageModel.id.asc(),
                    )
                )
                .scalars()
                .all()
            )
            last_turn = self._snapshot_last_turn(
                session,
                owner_id=user_ctx.user_id,
                task_id=task_id,
                messages=messages,
            )
            return ConversationTaskSnapshotResponse(
                request_id=request_id,
                task_id=task.id,
                memory_mode=EffectiveMemoryMode(task.effective_memory_mode),
                provider_mode=self._chat_provider.mode,
                model=self._chat_provider.model,
                messages=[_message_projection(message) for message in messages],
                last_turn=last_turn,
                last_event_seq=max(0, task.next_event_seq - 1),
                created_at=task.created_at,
                updated_at=task.updated_at,
            )

    def _snapshot_last_turn(
        self,
        session: Session,
        *,
        owner_id: str,
        task_id: str,
        messages: list[MessageModel],
    ) -> ConversationTurnStateProjection | None:
        latest_assistant = next(
            (
                message
                for message in reversed(messages)
                if message.role == MessageRole.ASSISTANT.value and message.run_id is not None
            ),
            None,
        )
        if latest_assistant is None or latest_assistant.turn_index is None:
            return None
        run = session.execute(
            select(AgentRunModel).where(
                and_(
                    AgentRunModel.id == latest_assistant.run_id,
                    AgentRunModel.owner_id == owner_id,
                    AgentRunModel.task_id == task_id,
                    AgentRunModel.status == "succeeded",
                )
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        chat_usage = _stage_usage_from_run(run)
        if chat_usage is None:
            return None

        judgment_rows = list(
            session.execute(
                select(MemoryLLMJudgeModel)
                .where(
                    and_(
                        MemoryLLMJudgeModel.owner_id == owner_id,
                        MemoryLLMJudgeModel.task_id == task_id,
                        MemoryLLMJudgeModel.run_id == run.id,
                        MemoryLLMJudgeModel.job_id.is_(None),
                        MemoryLLMJudgeModel.status == "completed",
                        MemoryLLMJudgeModel.judge_type.in_(
                            ("summary", "applicability", "tool_planning", "effect")
                        ),
                    )
                )
                .order_by(MemoryLLMJudgeModel.created_at.asc(), MemoryLLMJudgeModel.id.asc())
            )
            .scalars()
            .all()
        )
        applicability_rows = [row for row in judgment_rows if row.judge_type == "applicability"]
        effect_rows = {
            row.memory_id: row
            for row in judgment_rows
            if row.judge_type == "effect" and row.memory_id is not None
        }
        usage_rows = {
            row.memory_id: row
            for row in session.execute(
                select(MemoryUsageModel).where(
                    and_(
                        MemoryUsageModel.owner_id == owner_id,
                        MemoryUsageModel.task_id == task_id,
                        MemoryUsageModel.run_id == run.id,
                    )
                )
            )
            .scalars()
            .all()
        }

        decisions: list[TurnMemoryDecisionProjection] = []
        for row in applicability_rows:
            if row.memory_id is None or row.result_json is None:
                continue
            result = ApplicabilityJudgeResult.model_validate_json(row.result_json)
            receipt = usage_rows.get(row.memory_id)
            effect_row = effect_rows.get(row.memory_id)
            effect = None
            if effect_row is not None and effect_row.result_json is not None:
                effect = EffectJudgeResult.model_validate_json(effect_row.result_json).judgment
            decisions.append(
                TurnMemoryDecisionProjection(
                    memory_id=row.memory_id,
                    applicability=result.applicability,
                    reason_code=result.reason_code,
                    confidence=result.confidence,
                    injected=bool(receipt and receipt.injected),
                    estimated_tokens=receipt.estimated_tokens if receipt is not None else 0,
                    effect=effect,
                )
            )

        stage_usage = [
            projection
            for stage in ("summary", "applicability", "tool_planning")
            for row in judgment_rows
            if row.judge_type == stage
            if (projection := _stage_usage_from_judgment(stage, row)) is not None
        ]
        stage_usage.append(chat_usage)
        stage_usage.extend(
            projection
            for row in judgment_rows
            if row.judge_type == "effect"
            if (projection := _stage_usage_from_judgment("effect", row)) is not None
        )
        reflection_job = session.execute(
            select(MemoryReflectionJobModel).where(
                and_(
                    MemoryReflectionJobModel.owner_id == owner_id,
                    MemoryReflectionJobModel.task_id == task_id,
                    MemoryReflectionJobModel.run_id == run.id,
                )
            )
        ).scalar_one_or_none()
        tool_rows = list(
            session.execute(
                select(ToolCallModel)
                .where(
                    and_(
                        ToolCallModel.owner_id == owner_id,
                        ToolCallModel.task_id == task_id,
                        ToolCallModel.run_id == run.id,
                    )
                )
                .order_by(ToolCallModel.created_at.asc(), ToolCallModel.id.asc())
                .limit(1)
            )
            .scalars()
            .all()
        )
        return ConversationTurnStateProjection(
            run_id=run.id,
            turn_index=latest_assistant.turn_index,
            reflection_job_id=reflection_job.id if reflection_job is not None else None,
            memory_decisions=decisions,
            tool_calls=[_tool_projection(row) for row in tool_rows],
            usage=stage_usage,
        )

    def _begin_turn(
        self,
        user_ctx: UserContext,
        *,
        task_id: str,
        run_id: str,
        user_message_id: str,
        content: str,
        memory_mode: EffectiveMemoryMode | None,
    ) -> tuple[int, EffectiveMemoryMode, int]:
        with session_scope(self._session_factory) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            task = session.execute(
                select(TaskModel).where(
                    and_(
                        TaskModel.id == task_id,
                        TaskModel.owner_id == user_ctx.user_id,
                        TaskModel.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if task is None:
                raise LookupError("task_not_found")
            live_run = session.execute(
                select(AgentRunModel.id).where(
                    and_(
                        AgentRunModel.owner_id == user_ctx.user_id,
                        AgentRunModel.task_id == task_id,
                        AgentRunModel.schema_version == "2.0",
                        AgentRunModel.status.not_in(("succeeded", "failed", "cancelled")),
                    )
                )
            ).scalar_one_or_none()
            if live_run is not None:
                raise ConversationBusyError("conversation turn already in progress")
            effective = memory_mode or EffectiveMemoryMode(task.effective_memory_mode)
            turn_index = task.next_turn_index
            now = utc_now()
            session.add(
                AgentRunModel(
                    id=run_id,
                    owner_id=user_ctx.user_id,
                    task_id=task_id,
                    provider_mode=self._chat_provider.mode.value,
                    model=self._chat_provider.model,
                    status="retrieving",
                    stage="retrieving",
                    prompt_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                    reasoning_tokens=None,
                    token_source=(
                        "actual" if self._chat_provider.mode is ProviderMode.REAL else "mock"
                    ),
                    schema_version="2.0",
                    created_at=now,
                )
            )
            session.add(
                MessageModel(
                    id=user_message_id,
                    owner_id=user_ctx.user_id,
                    task_id=task_id,
                    run_id=run_id,
                    role=MessageRole.USER.value,
                    content=content,
                    turn_index=turn_index,
                    created_at=now,
                )
            )
            task.next_turn_index += 1
            task.updated_at = now
            event_seq = _append_task_event(
                session,
                task=task,
                event_type="turn.started",
                metadata={
                    "run_id": run_id,
                    "turn_index": turn_index,
                    "user_message_id": user_message_id,
                },
            )
            return turn_index, effective, event_seq

    def _load_context(
        self,
        user_ctx: UserContext,
        *,
        task_id: str,
        current_turn: str,
        memory_mode: EffectiveMemoryMode,
    ) -> tuple[list[MessageModel], list[MemoryCandidate], str | None]:
        with session_scope(self._session_factory) as session:
            task = session.execute(
                select(TaskModel).where(
                    and_(
                        TaskModel.id == task_id,
                        TaskModel.owner_id == user_ctx.user_id,
                        TaskModel.status == "active",
                    )
                )
            ).scalar_one()
            messages = list(
                session.execute(
                    select(MessageModel)
                    .where(
                        and_(
                            MessageModel.owner_id == user_ctx.user_id,
                            MessageModel.task_id == task_id,
                            MessageModel.turn_index.is_not(None),
                            MessageModel.turn_index > task.summary_through_turn,
                        )
                    )
                    .order_by(
                        MessageModel.turn_index.asc(),
                        MessageModel.created_at.asc(),
                        MessageModel.id.asc(),
                    )
                )
                .scalars()
                .all()
            )
            if memory_mode is EffectiveMemoryMode.OFF:
                return messages, [], task.conversation_summary
            count = session.execute(
                select(func.count())
                .select_from(MemoryCardModel)
                .where(
                    and_(
                        MemoryCardModel.owner_id == user_ctx.user_id,
                        MemoryCardModel.schema_version == "2.0",
                        MemoryCardModel.review_status == ReviewStatus.ACTIVE.value,
                        MemoryCardModel.status == "active",
                    )
                )
            ).scalar_one()
            query = (
                select(MemoryCardModel, MemoryVersionModel)
                .join(
                    MemoryVersionModel,
                    and_(
                        MemoryVersionModel.id == MemoryCardModel.current_version_id,
                        MemoryVersionModel.owner_id == user_ctx.user_id,
                    ),
                )
                .where(
                    and_(
                        MemoryCardModel.owner_id == user_ctx.user_id,
                        MemoryCardModel.schema_version == "2.0",
                        MemoryCardModel.review_status == ReviewStatus.ACTIVE.value,
                        MemoryCardModel.status == "active",
                    )
                )
            )
            if count > self._settings.memory_max_candidates:
                ids = _fts_candidate_ids(
                    session,
                    owner_id=user_ctx.user_id,
                    current_turn=current_turn,
                    limit=self._settings.memory_max_candidates,
                )
                if not ids:
                    return messages, [], task.conversation_summary
                query = query.where(MemoryCardModel.id.in_(ids))
            rows = session.execute(
                query.order_by(
                    MemoryCardModel.updated_at.desc(),
                    MemoryCardModel.id.asc(),
                ).limit(self._settings.memory_max_candidates)
            ).all()
            return (
                messages,
                [MemoryCandidate(card=card, version=version) for card, version in rows],
                task.conversation_summary,
            )

    async def _prepare_history(
        self,
        user_ctx: UserContext,
        *,
        task_id: str,
        run_id: str,
        history_rows: list[MessageModel],
        existing_summary: str | None,
    ) -> tuple[tuple[ProviderMessage, ...], str | None, SummaryCall | None]:
        history = tuple(
            ProviderMessage(role=message.role, content=message.content) for message in history_rows
        )
        estimated = estimate_tokens(existing_summary or "") + sum(
            estimate_tokens(message.content) for message in history_rows
        )
        if estimated <= self._settings.conversation_context_token_budget:
            return history, existing_summary, None
        # Never summarize the current user turn. Busy-turn exclusion guarantees
        # it is the last unsummarized row and no later turn can race this call.
        to_summarize = history_rows[:-1]
        if not to_summarize:
            return history, existing_summary, None
        through_turn = max(message.turn_index or 0 for message in to_summarize)
        payload = json.dumps(
            {
                "previous_summary": existing_summary or "",
                "messages": [
                    {
                        "role": message.role,
                        "turn_index": message.turn_index,
                        "content": message.content,
                    }
                    for message in to_summarize
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        schema = {
            "name": "conversation_rolling_summary",
            "schema": RollingSummaryWireResult.model_json_schema(),
            "strict": True,
        }
        output = await self._semantic_provider.complete_json(
            ProviderRequest(
                task_text=(
                    "Compress the supplied completed conversation turns into a concise, "
                    "fact-preserving context summary for the same conversation. Preserve "
                    "unresolved questions and explicit current preferences, but do not "
                    "create or label long-term memory. Return only the strict schema.\n\n"
                    "INPUT_JSON\n" + payload
                ),
                output_schema=schema,
                stage="summary",
            ),
            schema,
        )
        result = RollingSummaryWireResult.model_validate(output.parsed)
        if estimate_tokens(result.summary) > self._settings.conversation_context_token_budget:
            raise RuntimeError("rolling summary exceeds the configured context budget")
        call = SummaryCall(
            summary=result.summary,
            through_turn_index=through_turn,
            provider=output,
        )
        self._persist_summary(
            user_ctx,
            task_id=task_id,
            run_id=run_id,
            call=call,
        )
        remaining = tuple(
            ProviderMessage(role=message.role, content=message.content)
            for message in history_rows
            if (message.turn_index or 0) > through_turn
        )
        return remaining, call.summary, call

    def _persist_summary(
        self,
        user_ctx: UserContext,
        *,
        task_id: str,
        run_id: str,
        call: SummaryCall,
    ) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            task = session.execute(
                select(TaskModel).where(
                    and_(
                        TaskModel.id == task_id,
                        TaskModel.owner_id == user_ctx.user_id,
                        TaskModel.status == "active",
                    )
                )
            ).scalar_one()
            if task.summary_through_turn >= call.through_turn_index:
                return
            task.conversation_summary = call.summary
            task.summary_through_turn = call.through_turn_index
            task.updated_at = utc_now()
            _add_judgment(
                session,
                owner_id=user_ctx.user_id,
                task_id=task_id,
                run_id=run_id,
                memory_id=None,
                judge_type="summary",
                result_json=RollingSummaryWireResult(summary=call.summary).model_dump_json(),
                provider=call.provider,
                provider_mode=self._semantic_provider.mode,
            )

    async def _judge_applicability(
        self,
        *,
        current_turn: str,
        candidates: list[MemoryCandidate],
    ) -> list[ApplicabilityCall]:
        semantic_data = [candidate.semantic_data() for candidate in candidates]
        calls: list[ApplicabilityCall] = []
        for candidate in candidates:
            other = [item for item in semantic_data if item["memory_id"] != candidate.card.id]
            call = await self._applicability.judge_call(
                current_turn=current_turn,
                candidate_memory=candidate.semantic_data(),
                active_memories=other,
            )
            calls.append(ApplicabilityCall(candidate=candidate, call=call))
        return calls

    async def _plan_tool(
        self,
        *,
        content: str,
        history: tuple[ProviderMessage, ...],
        conversation_summary: str | None,
    ) -> ToolPlanningCall | None:
        candidates = extract_python_candidates(content)
        if not candidates:
            return None
        function_call = getattr(self._chat_provider, "function_call", None)
        if not callable(function_call):
            raise ProviderFailure(
                AsyncErrorCode.PROVIDER_ERROR,
                "当前真实模型未提供冻结的 function calling 能力。",
                retryable=False,
                failure_kind="tool_planning_unsupported",
            )
        allowed_ids = [candidate.code_block_id for candidate in candidates]
        tools = [
            {
                "type": "function",
                "name": "python_ast_check",
                "description": (
                    "Statically parse one server-enumerated Python candidate with ast.parse. "
                    "It never executes code and must be selected only when syntax validation "
                    "materially helps answer the current user turn."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code_block_id": {
                            "type": "string",
                            "enum": allowed_ids,
                            "description": "Server-issued identifier for a bounded code block.",
                        }
                    },
                    "required": ["code_block_id"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        ]
        output = await function_call(
            ProviderRequest(
                task_text=content,
                conversation=history,
                conversation_summary=conversation_summary,
                stage="tool_planning",
            ),
            tools,
        )
        if output.model != self._chat_provider.model or output.usage.total_tokens is None:
            raise ProviderFailure(
                AsyncErrorCode.PROVIDER_ERROR,
                "工具规划未返回冻结模型的完整实际 usage。",
                retryable=False,
                failure_kind="tool_planning_usage_invalid",
            )
        if len(output.calls) > 1:
            raise ProviderFailure(
                AsyncErrorCode.TOOL_INPUT_INVALID,
                "模型返回了超过白名单上限的工具调用。",
                retryable=False,
                failure_kind="tool_call_cardinality_invalid",
            )
        if not output.calls:
            return ToolPlanningCall(
                provider=output,
                candidate=None,
                execution=None,
                tool_call_id=None,
                result_ref=None,
            )
        call = output.calls[0]
        if call.name != "python_ast_check":
            raise ProviderFailure(
                AsyncErrorCode.TOOL_NOT_FOUND,
                "模型请求了不在白名单中的工具。",
                retryable=False,
                failure_kind="tool_not_allowed",
            )
        try:
            arguments = json.loads(call.arguments)
        except json.JSONDecodeError as exc:
            raise ProviderFailure(
                AsyncErrorCode.TOOL_INPUT_INVALID,
                "模型返回了无效的工具参数。",
                retryable=False,
                failure_kind="tool_arguments_json_invalid",
            ) from exc
        if not isinstance(arguments, dict) or set(arguments) != {"code_block_id"}:
            raise ProviderFailure(
                AsyncErrorCode.TOOL_INPUT_INVALID,
                "模型返回了超出冻结 Schema 的工具参数。",
                retryable=False,
                failure_kind="tool_arguments_schema_invalid",
            )
        code_block_id = arguments.get("code_block_id")
        candidate = next(
            (item for item in candidates if item.code_block_id == code_block_id),
            None,
        )
        if candidate is None:
            raise ProviderFailure(
                AsyncErrorCode.TOOL_INPUT_INVALID,
                "模型引用了不存在的服务端代码块。",
                retryable=False,
                failure_kind="tool_code_block_unknown",
            )
        try:
            execution = self._tools.run("python_ast_check", candidate)
        except ToolFailure as exc:
            raise ProviderFailure(
                exc.code,
                "静态工具拒绝了该输入。",
                retryable=False,
                failure_kind="tool_execution_rejected",
            ) from exc
        return ToolPlanningCall(
            provider=output,
            candidate=candidate,
            execution=execution,
            tool_call_id=new_prefixed_ulid("tool"),
            result_ref=new_prefixed_ulid("toolres"),
        )

    def _persist_tool_plan(
        self,
        user_ctx: UserContext,
        *,
        task_id: str,
        run_id: str,
        turn_index: int,
        plan: ToolPlanningCall,
    ) -> tuple[ToolCallSnapshot | None, int]:
        projection: ToolCallSnapshot | None = None
        now = utc_now()
        with session_scope(self._session_factory) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            task = session.execute(
                select(TaskModel).where(
                    and_(
                        TaskModel.id == task_id,
                        TaskModel.owner_id == user_ctx.user_id,
                    )
                )
            ).scalar_one()
            _add_judgment(
                session,
                owner_id=user_ctx.user_id,
                task_id=task_id,
                run_id=run_id,
                memory_id=None,
                judge_type="tool_planning",
                result_json=json.dumps(
                    {
                        "action": "call" if plan.candidate is not None else "skip",
                        "tool_name": ("python_ast_check" if plan.candidate is not None else None),
                    },
                    separators=(",", ":"),
                ),
                provider=plan.provider,
                provider_mode=self._chat_provider.mode,
            )
            if (
                plan.candidate is not None
                and plan.execution is not None
                and plan.execution.result is not None
                and plan.tool_call_id is not None
                and plan.result_ref is not None
            ):
                projection = ToolCallSnapshot(
                    tool_call_id=plan.tool_call_id,
                    reason="模型选择了允许的 Python AST 静态检查",
                    args_summary=plan.candidate.summary,
                    status=ToolCallStatus.SUCCEEDED,
                    latency_ms=plan.execution.latency_ms,
                    result_ref=plan.result_ref,
                    result=plan.execution.result,
                )
                session.add(
                    ToolCallModel(
                        id=plan.tool_call_id,
                        owner_id=user_ctx.user_id,
                        task_id=task_id,
                        run_id=run_id,
                        tool_name="python_ast_check",
                        reason="model_selected_allowed_tool",
                        args_summary_json=json.dumps(
                            {
                                "language": "python",
                                "code_source": plan.candidate.source.value,
                                "code_bytes": plan.candidate.byte_count,
                                "code_block_id": plan.candidate.code_block_id,
                            },
                            separators=(",", ":"),
                        ),
                        result_summary_json=plan.execution.result.model_dump_json(),
                        status="succeeded",
                        duration_ms=plan.execution.latency_ms,
                        result_ref=plan.result_ref,
                        provider_mode=self._chat_provider.mode.value,
                        provider_model=plan.provider.model,
                        prompt_hash=plan.provider.prompt_hash,
                        prompt_tokens=plan.provider.usage.prompt_tokens,
                        output_tokens=plan.provider.usage.output_tokens,
                        total_tokens=plan.provider.usage.total_tokens,
                        token_source=(
                            "actual" if self._chat_provider.mode is ProviderMode.REAL else "mock"
                        ),
                        provider_latency_ms=plan.provider.latency_ms,
                        created_at=now,
                    )
                )
            event_seq = _append_task_event(
                session,
                task=task,
                event_type=(
                    "conversation.tool.completed"
                    if projection is not None
                    else "conversation.tool.skipped"
                ),
                metadata=_tool_event_metadata(
                    run_id=run_id,
                    turn_index=turn_index,
                    plan=plan,
                ),
            )
        return projection, event_seq

    async def _chat(
        self,
        *,
        user_ctx: UserContext,
        task_id: str,
        run_id: str,
        content: str,
        history: tuple[ProviderMessage, ...],
        conversation_summary: str | None,
        memory_context: str | None,
        usage_ids: tuple[str, ...],
        tool_result: PythonAstResult | None,
    ) -> ChatCall:
        answer_parts: list[str] = []
        final: ProviderStreamItem | None = None
        delta_index = 0
        async for item in self._chat_provider.stream(
            ProviderRequest(
                task_text=content,
                conversation=history,
                conversation_summary=conversation_summary,
                memory_context=memory_context,
                usage_ids=usage_ids,
                tool_result=tool_result,
                stage="chat",
            )
        ):
            if item.delta:
                answer_parts.append(item.delta)
                delta_index += 1
                if self._stream_hub is not None:
                    await self._stream_hub.publish_delta(
                        owner_id=user_ctx.user_id,
                        task_id=task_id,
                        run_id=run_id,
                        delta_index=delta_index,
                        delta=item.delta,
                    )
            if item.finish_reason is not None:
                final = item
        if final is None or final.usage is None or final.prompt_hash is None:
            raise RuntimeError("chat provider did not return final actual usage")
        answer = "".join(answer_parts)
        if not answer:
            raise RuntimeError("chat provider returned an empty answer")
        return ChatCall(answer=answer, final=final)

    async def _judge_effects(
        self,
        *,
        current_turn: str,
        compiled: list[CompiledMemory],
        answer: str,
    ) -> list[tuple[CompiledMemory, JudgeCall[EffectJudgeResult]]]:
        results: list[tuple[CompiledMemory, JudgeCall[EffectJudgeResult]]] = []
        for item in compiled:
            call = await self._effect.judge_call(
                current_turn=current_turn,
                memory=item.candidate.semantic_data(),
                assistant_answer=answer,
            )
            results.append((item, call))
        return results

    def _persist_retrieval(
        self,
        user_ctx: UserContext,
        *,
        request_id: str,
        task_id: str,
        run_id: str,
        candidates: list[MemoryCandidate],
        calls: list[ApplicabilityCall],
        compiled: list[CompiledMemory],
        memory_mode: EffectiveMemoryMode,
    ) -> tuple[tuple[str, ...], str]:
        compiled_ids = {item.candidate.card.id for item in compiled}
        selected_calls = [
            item
            for item in calls
            if item.call.result.applicability is ApplicabilityResult.APPLICABLE
        ]
        selected_ids = {item.candidate.card.id for item in selected_calls}
        usage_ids: list[str] = []
        usage_by_memory: dict[str, str] = {}
        trace_id = new_prefixed_ulid("trace")
        now = utc_now()
        section = _compile_section(compiled)
        with session_scope(self._session_factory) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            trace_row = RetrievalTraceModel(
                id=trace_id,
                owner_id=user_ctx.user_id,
                request_id=request_id,
                task_id=task_id,
                run_id=run_id,
                retrieval_mode="llm_judge",
                algorithm_version="llm_applicability_v1",
                threshold=0,
                top_k=self._settings.memory_top_k,
                candidate_count=len(candidates),
                retrieved_count=len(candidates),
                selected_count=len(selected_ids),
                injected_count=len(compiled_ids),
                decisions_json="[]",
                retrieval_ms=0,
                memory_chars=len(section or ""),
                memory_tokens_estimated=estimate_tokens(section or ""),
                provider_prompt_tokens_actual=None,
                prompt_section_hash=(
                    hashlib.sha256(section.encode()).hexdigest() if section else None
                ),
                reason_codes_json=json.dumps(
                    ["memory_mode_off"] if memory_mode is EffectiveMemoryMode.OFF else []
                ),
                created_at=now,
                updated_at=now,
            )
            session.add(trace_row)
            # No ORM relationship connects a trace to its receipt rows. Flush
            # the parent explicitly so SQLite can enforce the usage FK without
            # depending on unit-of-work insertion ordering.
            session.flush([trace_row])
            for rank, item in enumerate(calls, start=1):
                card = session.get(MemoryCardModel, item.candidate.card.id)
                if card is None or card.owner_id != user_ctx.user_id:
                    raise RuntimeError("owner-scoped candidate disappeared")
                result = item.call.result
                selected = card.id in selected_ids
                injected = card.id in compiled_ids
                session.add(
                    RetrievalDecisionModel(
                        id=new_prefixed_ulid("rdec"),
                        owner_id=user_ctx.user_id,
                        retrieval_trace_id=trace_id,
                        memory_id=card.id,
                        memory_version_id=card.current_version_id,
                        memory_status=card.review_status or "active",
                        retrieved=True,
                        selected=selected,
                        injected=injected,
                        rank=rank,
                        scope_match=None,
                        semantic_similarity=None,
                        provenance_confidence=card.confidence,
                        verified_effect=None,
                        recency=None,
                        final_score=result.confidence,
                        reason_codes_json=json.dumps([result.reason_code.value]),
                        created_at=now,
                    )
                )
                _add_judgment(
                    session,
                    owner_id=user_ctx.user_id,
                    task_id=task_id,
                    run_id=run_id,
                    memory_id=card.id,
                    judge_type="applicability",
                    result_json=result.model_dump_json(),
                    provider=item.call.provider,
                    provider_mode=self._semantic_provider.mode,
                )
                card.retrieved_count += 1
                if selected:
                    compiled_item = next(
                        (entry for entry in compiled if entry.candidate.card.id == card.id),
                        None,
                    )
                    usage_id = new_prefixed_ulid("usage")
                    usage_by_memory[card.id] = usage_id
                    if injected:
                        usage_ids.append(usage_id)
                    session.add(
                        MemoryUsageModel(
                            id=usage_id,
                            owner_id=user_ctx.user_id,
                            retrieval_trace_id=trace_id,
                            task_id=task_id,
                            run_id=run_id,
                            memory_id=card.id,
                            memory_version_id=card.current_version_id,
                            rank=rank,
                            retrieved=True,
                            selected=True,
                            injected=injected,
                            estimated_tokens=(
                                compiled_item.estimated_tokens if compiled_item else 0
                            ),
                            verification_status="pending" if injected else "unknown",
                            verification_method=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                if injected:
                    card.injected_count += 1
                    card.last_used_at = now
            trace = session.get(RetrievalTraceModel, trace_id)
            if trace is not None:
                trace.decisions_json = json.dumps(
                    [
                        {
                            "memory_id": item.candidate.card.id,
                            "applicability": item.call.result.applicability.value,
                            "reason_code": item.call.result.reason_code.value,
                            "selected": item.candidate.card.id in selected_ids,
                            "injected": item.candidate.card.id in compiled_ids,
                        }
                        for item in calls
                    ],
                    separators=(",", ":"),
                )
        return tuple(usage_ids), trace_id

    def _commit_turn(
        self,
        user_ctx: UserContext,
        *,
        task_id: str,
        run_id: str,
        trace_id: str,
        turn_index: int,
        user_message_id: str,
        assistant_message_id: str,
        answer: str,
        chat: ChatCall,
        compiled: list[CompiledMemory],
        applicability_calls: list[ApplicabilityCall],
        effects: list[tuple[CompiledMemory, JudgeCall[EffectJudgeResult]]],
        reflection_job_id: MemoryReflectionJobId | None,
    ) -> tuple[
        ConversationMessageProjection,
        ConversationMessageProjection,
        list[TurnMemoryDecisionProjection],
        int,
    ]:
        now = utc_now()
        effect_by_memory = {item.candidate.card.id: call for item, call in effects}
        compiled_by_memory = {item.candidate.card.id: item for item in compiled}
        with session_scope(self._session_factory) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            run = session.execute(
                select(AgentRunModel).where(
                    and_(
                        AgentRunModel.id == run_id,
                        AgentRunModel.owner_id == user_ctx.user_id,
                        AgentRunModel.task_id == task_id,
                    )
                )
            ).scalar_one()
            final = chat.final
            usage = final.usage
            if usage is None:
                raise RuntimeError("chat usage disappeared")
            run.status = "succeeded"
            run.stage = "succeeded"
            run.prompt_tokens = usage.prompt_tokens
            run.output_tokens = usage.output_tokens
            run.total_tokens = usage.total_tokens
            run.reasoning_tokens = usage.reasoning_tokens
            run.token_source = "actual" if self._chat_provider.mode is ProviderMode.REAL else "mock"
            run.provider_response_id = final.response_id
            run.prompt_hash = final.prompt_hash
            run.first_token_ms = final.first_token_ms
            run.total_ms = final.latency_ms
            run.completed_at = now
            assistant = MessageModel(
                id=assistant_message_id,
                owner_id=user_ctx.user_id,
                task_id=task_id,
                run_id=run_id,
                role=MessageRole.ASSISTANT.value,
                content=answer,
                turn_index=turn_index,
                created_at=now,
            )
            session.add(assistant)
            if reflection_job_id is not None:
                # No ORM relationship declares the assistant-message FK edge,
                # so flush the message before inserting the durable job.
                session.flush([assistant])
                session.add(
                    MemoryReflectionJobModel(
                        id=reflection_job_id,
                        owner_id=user_ctx.user_id,
                        task_id=task_id,
                        run_id=run_id,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                        turn_index=turn_index,
                        status="pending",
                        attempt=0,
                        provider_model=self._semantic_provider.model,
                        schema_version="2.0",
                        created_at=now,
                        updated_at=now,
                    )
                )
            trace = session.execute(
                select(RetrievalTraceModel).where(
                    and_(
                        RetrievalTraceModel.id == trace_id,
                        RetrievalTraceModel.owner_id == user_ctx.user_id,
                    )
                )
            ).scalar_one()
            trace.provider_prompt_tokens_actual = usage.prompt_tokens
            trace.updated_at = now
            for memory_id, call in effect_by_memory.items():
                usage_row = session.execute(
                    select(MemoryUsageModel).where(
                        and_(
                            MemoryUsageModel.owner_id == user_ctx.user_id,
                            MemoryUsageModel.run_id == run_id,
                            MemoryUsageModel.memory_id == memory_id,
                            MemoryUsageModel.injected.is_(True),
                        )
                    )
                ).scalar_one()
                result = call.result
                usage_row.verification_status = result.judgment.value
                usage_row.verification_method = "structured_provider"
                usage_row.evidence_excerpt = result.evidence_excerpt
                usage_row.updated_at = now
                card = session.get(MemoryCardModel, memory_id)
                if card is not None and result.judgment.value == "applied":
                    card.verified_applied_count += 1
                _add_judgment(
                    session,
                    owner_id=user_ctx.user_id,
                    task_id=task_id,
                    run_id=run_id,
                    memory_id=memory_id,
                    judge_type="effect",
                    result_json=result.model_dump_json(),
                    provider=call.provider,
                    provider_mode=self._semantic_provider.mode,
                )
                _append_owner_event(
                    session,
                    owner_id=user_ctx.user_id,
                    event_type="memory.effect.judged",
                    metadata={
                        "memory_id": memory_id,
                        "run_id": run_id,
                        "reason_code": result.reason_code.value,
                        "judgment": result.judgment.value,
                    },
                )
            task = session.execute(
                select(TaskModel).where(
                    and_(
                        TaskModel.id == task_id,
                        TaskModel.owner_id == user_ctx.user_id,
                    )
                )
            ).scalar_one()
            task.updated_at = now
            completed_event_seq = _append_task_event(
                session,
                task=task,
                event_type="turn.completed",
                metadata={
                    "run_id": run_id,
                    "turn_index": turn_index,
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id,
                    "reflection_pending": reflection_job_id is not None,
                    "job_id": reflection_job_id,
                },
            )
            user_message = session.get(MessageModel, user_message_id)
            if user_message is None:
                raise RuntimeError("user message disappeared")
            session.flush()
            decisions = [
                TurnMemoryDecisionProjection(
                    memory_id=item.candidate.card.id,
                    applicability=item.call.result.applicability,
                    reason_code=item.call.result.reason_code,
                    confidence=item.call.result.confidence,
                    injected=item.candidate.card.id in compiled_by_memory,
                    estimated_tokens=(
                        compiled_by_memory[item.candidate.card.id].estimated_tokens
                        if item.candidate.card.id in compiled_by_memory
                        else 0
                    ),
                    effect=(
                        effect_by_memory[item.candidate.card.id].result.judgment
                        if item.candidate.card.id in effect_by_memory
                        else None
                    ),
                )
                for item in applicability_calls
            ]
            user_projection = _message_projection(user_message)
            assistant_projection = _message_projection(assistant)
        return user_projection, assistant_projection, decisions, completed_event_seq

    def _fail_run(
        self,
        user_ctx: UserContext,
        *,
        task_id: str,
        run_id: str,
        error_code: str,
    ) -> int | None:
        with session_scope(self._session_factory) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            run = session.execute(
                select(AgentRunModel).where(
                    and_(
                        AgentRunModel.id == run_id,
                        AgentRunModel.owner_id == user_ctx.user_id,
                        AgentRunModel.task_id == task_id,
                    )
                )
            ).scalar_one_or_none()
            if run is not None and run.status != "succeeded":
                user_message = session.execute(
                    select(MessageModel).where(
                        and_(
                            MessageModel.owner_id == user_ctx.user_id,
                            MessageModel.task_id == task_id,
                            MessageModel.run_id == run_id,
                            MessageModel.role == MessageRole.USER.value,
                        )
                    )
                ).scalar_one_or_none()
                turn_index = user_message.turn_index if user_message is not None else None
                decisions = list(
                    session.execute(
                        select(RetrievalDecisionModel).where(
                            and_(
                                RetrievalDecisionModel.owner_id == user_ctx.user_id,
                                RetrievalDecisionModel.retrieval_trace_id.in_(
                                    select(RetrievalTraceModel.id).where(
                                        and_(
                                            RetrievalTraceModel.owner_id == user_ctx.user_id,
                                            RetrievalTraceModel.run_id == run_id,
                                        )
                                    )
                                ),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                injected_memory_ids = {
                    decision.memory_id for decision in decisions if decision.injected
                }
                for decision in decisions:
                    card = session.get(MemoryCardModel, decision.memory_id)
                    if card is None or card.owner_id != user_ctx.user_id:
                        continue
                    if decision.retrieved:
                        card.retrieved_count = max(0, card.retrieved_count - 1)
                    if decision.injected:
                        card.injected_count = max(0, card.injected_count - 1)
                session.execute(
                    delete(MemoryLLMJudgeModel).where(
                        and_(
                            MemoryLLMJudgeModel.owner_id == user_ctx.user_id,
                            MemoryLLMJudgeModel.run_id == run_id,
                            MemoryLLMJudgeModel.judge_type.in_(("applicability", "effect")),
                        )
                    )
                )
                session.execute(
                    delete(RetrievalTraceModel).where(
                        and_(
                            RetrievalTraceModel.owner_id == user_ctx.user_id,
                            RetrievalTraceModel.run_id == run_id,
                        )
                    )
                )
                session.flush()
                for memory_id in injected_memory_ids:
                    card = session.get(MemoryCardModel, memory_id)
                    if card is not None and card.owner_id == user_ctx.user_id:
                        card.last_used_at = session.execute(
                            select(func.max(MemoryUsageModel.created_at)).where(
                                and_(
                                    MemoryUsageModel.owner_id == user_ctx.user_id,
                                    MemoryUsageModel.memory_id == memory_id,
                                    MemoryUsageModel.injected.is_(True),
                                )
                            )
                        ).scalar_one()
                run.status = "failed"
                run.stage = "failed"
                run.error_code = error_code
                run.completed_at = utc_now()
                task = session.execute(
                    select(TaskModel).where(
                        and_(
                            TaskModel.id == task_id,
                            TaskModel.owner_id == user_ctx.user_id,
                        )
                    )
                ).scalar_one_or_none()
                if task is not None:
                    task.updated_at = utc_now()
                    return _append_task_event(
                        session,
                        task=task,
                        event_type="turn.failed",
                        metadata={
                            "run_id": run_id,
                            "turn_index": turn_index,
                            "error_code": error_code,
                        },
                    )
        return None


def _compile_memories(
    calls: list[ApplicabilityCall],
    *,
    per_card_budget: int,
    total_budget: int,
    top_k: int,
) -> list[CompiledMemory]:
    applicable = [
        item for item in calls if item.call.result.applicability is ApplicabilityResult.APPLICABLE
    ]
    applicable.sort(
        key=lambda item: (
            -item.call.result.confidence,
            item.candidate.card.id,
        )
    )
    compiled: list[CompiledMemory] = []
    for item in applicable[:top_k]:
        content = item.candidate.card.content or ""
        block = _memory_block(item.candidate, content=content)
        while estimate_tokens(block) > per_card_budget and content:
            shrink_by = max(8, len(content) // 8)
            content = content[: max(0, len(content) - shrink_by)]
            rendered = content + ("…" if content else "")
            block = _memory_block(item.candidate, content=rendered)
        tokens = estimate_tokens(block)
        if tokens > per_card_budget:
            continue
        candidate_compiled = CompiledMemory(
            candidate=item.candidate,
            judgment=item.call.result,
            block=block,
            estimated_tokens=tokens,
        )
        proposed = [*compiled, candidate_compiled]
        if estimate_tokens(_compile_section(proposed) or "") > total_budget:
            continue
        compiled.append(candidate_compiled)
    return compiled


def _memory_block(candidate: MemoryCandidate, *, content: str | None = None) -> str:
    card = candidate.card
    return (
        f'<MEMORY id="{card.id}" kind="{escape_xml(card.memory_kind_v2 or "")}">\n'
        f"<APPLIES_WHEN>{escape_xml(card.applies_when or '')}</APPLIES_WHEN>\n"
        f"<CONTENT>{escape_xml(content if content is not None else card.content or '')}</CONTENT>\n"
        "</MEMORY>"
    )


def _compile_section(compiled: list[CompiledMemory]) -> str | None:
    if not compiled:
        return None
    return CONTEXT_OPEN + "\n" + "\n".join(item.block for item in compiled) + "\n" + CONTEXT_CLOSE


def _add_judgment(
    session: Session,
    *,
    owner_id: str,
    task_id: str,
    run_id: str,
    memory_id: str | None,
    judge_type: str,
    result_json: str,
    provider: StructuredOutput | FunctionCallOutput,
    provider_mode: ProviderMode,
) -> None:
    session.add(
        MemoryLLMJudgeModel(
            id=new_prefixed_ulid("judge"),
            owner_id=owner_id,
            job_id=None,
            task_id=task_id,
            run_id=run_id,
            memory_id=memory_id,
            judge_type=judge_type,
            status="completed",
            result_json=result_json,
            error_code=None,
            provider_model=provider.model,
            prompt_hash=provider.prompt_hash,
            schema_version="2.0",
            input_tokens=provider.usage.prompt_tokens,
            output_tokens=provider.usage.output_tokens,
            total_tokens=provider.usage.total_tokens,
            latency_ms=provider.latency_ms,
            token_source="actual" if provider_mode is ProviderMode.REAL else "mock",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )


def _append_task_event(
    session: Session,
    *,
    task: TaskModel,
    event_type: str,
    metadata: dict[str, object],
) -> int:
    seq = task.next_event_seq
    task.next_event_seq += 1
    session.add(
        EventLogModel(
            id=new_prefixed_ulid("evt"),
            owner_id=task.owner_id,
            stream_type="task",
            stream_id=task.id,
            seq=seq,
            event_type=event_type,
            metadata_json=json.dumps(metadata, separators=(",", ":")),
            created_at=utc_now(),
        )
    )
    return seq


def _append_owner_event(
    session: Session,
    *,
    owner_id: str,
    event_type: str,
    metadata: dict[str, object],
) -> int:
    cursor = session.get(MemoryEventCursorModel, owner_id)
    if cursor is None:
        cursor = MemoryEventCursorModel(owner_id=owner_id, next_seq=1, updated_at=utc_now())
        session.add(cursor)
        session.flush([cursor])
    seq = cursor.next_seq
    cursor.next_seq += 1
    cursor.updated_at = utc_now()
    session.add(
        EventLogModel(
            id=new_prefixed_ulid("evt"),
            owner_id=owner_id,
            stream_type="owner_memory",
            stream_id=owner_id,
            seq=seq,
            event_type=event_type,
            metadata_json=json.dumps(metadata, separators=(",", ":")),
            created_at=utc_now(),
        )
    )
    return seq


def _message_projection(message: MessageModel) -> ConversationMessageProjection:
    if message.turn_index is None:
        raise ValueError("conversation message has no turn index")
    return ConversationMessageProjection(
        message_id=message.id,
        run_id=message.run_id,
        role=MessageRole(message.role),
        content=message.content,
        turn_index=message.turn_index,
        created_at=message.created_at,
    )


def _tool_projection(row: ToolCallModel) -> ToolCallSnapshot:
    args = json.loads(row.args_summary_json)
    if not isinstance(args, dict):
        raise ValueError("persisted tool args summary is invalid")
    result = (
        PythonAstResult.model_validate_json(row.result_summary_json)
        if row.result_summary_json is not None
        else None
    )
    return ToolCallSnapshot(
        tool_call_id=row.id,
        reason="模型选择了允许的 Python AST 静态检查",
        args_summary=ToolArgsSummary(
            code_source=args.get("code_source"),
            code_bytes=args.get("code_bytes"),
        ),
        status=ToolCallStatus(row.status),
        latency_ms=row.duration_ms,
        result_ref=row.result_ref,
        result=result,
    )


def _tool_event_metadata(
    *,
    run_id: str,
    turn_index: int,
    plan: ToolPlanningCall,
) -> dict[str, object]:
    called = plan.candidate is not None and plan.execution is not None
    metadata: dict[str, object] = {
        "run_id": run_id,
        "turn_index": turn_index,
        "action": "call" if called else "skip",
        "reason_code": "model_selected_allowed_tool" if called else "model_skipped_tool",
        "model": plan.provider.model,
        "input_tokens": plan.provider.usage.prompt_tokens,
        "output_tokens": plan.provider.usage.output_tokens,
        "total_tokens": plan.provider.usage.total_tokens,
        "provider_latency_ms": plan.provider.latency_ms,
    }
    if called and plan.candidate is not None and plan.execution is not None:
        metadata.update(
            {
                "tool_name": "python_ast_check",
                "tool_call_id": plan.tool_call_id,
                "status": plan.execution.status,
                "code_source": plan.candidate.source.value,
                "code_bytes": plan.candidate.byte_count,
                "valid": (
                    plan.execution.result.valid if plan.execution.result is not None else None
                ),
                "latency_ms": plan.execution.latency_ms,
                "result_ref": plan.result_ref,
            }
        )
    return metadata


def _stage_usage(
    stage: str,
    output: StructuredOutput,
    provider: StructuredProvider,
) -> StageUsageProjection:
    return StageUsageProjection(
        stage=stage,
        provider_mode=provider.mode,
        model=output.model,
        prompt_hash=output.prompt_hash,
        input_tokens=output.usage.prompt_tokens,
        output_tokens=output.usage.output_tokens,
        total_tokens=output.usage.total_tokens,
        reasoning_tokens=output.usage.reasoning_tokens,
        latency_ms=output.latency_ms,
        first_token_ms=None,
    )


def _stage_usage_from_function(
    output: FunctionCallOutput,
    provider: StreamingProvider,
) -> StageUsageProjection:
    if output.usage.total_tokens is None:
        raise ValueError("tool planning usage is incomplete")
    return StageUsageProjection(
        stage="tool_planning",
        provider_mode=provider.mode,
        model=output.model,
        prompt_hash=output.prompt_hash,
        input_tokens=output.usage.prompt_tokens,
        output_tokens=output.usage.output_tokens,
        total_tokens=output.usage.total_tokens,
        reasoning_tokens=output.usage.reasoning_tokens,
        latency_ms=output.latency_ms,
        first_token_ms=None,
    )


def _stage_usage_from_stream(
    item: ProviderStreamItem,
    provider: StreamingProvider,
) -> StageUsageProjection:
    usage = item.usage
    if (
        usage is None
        or usage.total_tokens is None
        or item.prompt_hash is None
        or item.model is None
        or item.latency_ms is None
    ):
        raise ValueError("stream usage is incomplete")
    return StageUsageProjection(
        stage="chat",
        provider_mode=provider.mode,
        model=item.model,
        prompt_hash=item.prompt_hash,
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        latency_ms=item.latency_ms,
        first_token_ms=item.first_token_ms,
    )


def _stage_usage_from_run(run: AgentRunModel) -> StageUsageProjection | None:
    if (
        run.prompt_hash is None
        or run.prompt_tokens is None
        or run.output_tokens is None
        or run.total_tokens is None
        or run.total_ms is None
    ):
        return None
    return StageUsageProjection(
        stage="chat",
        provider_mode=ProviderMode(run.provider_mode),
        model=run.model,
        prompt_hash=run.prompt_hash,
        input_tokens=run.prompt_tokens,
        output_tokens=run.output_tokens,
        total_tokens=run.total_tokens,
        reasoning_tokens=run.reasoning_tokens,
        latency_ms=max(0, round(run.total_ms)),
        first_token_ms=(
            max(0, round(run.first_token_ms)) if run.first_token_ms is not None else None
        ),
    )


def _stage_usage_from_judgment(
    stage: str,
    row: MemoryLLMJudgeModel,
) -> StageUsageProjection | None:
    if (
        row.input_tokens is None
        or row.output_tokens is None
        or row.total_tokens is None
        or row.latency_ms is None
    ):
        return None
    return StageUsageProjection(
        stage=stage,
        provider_mode=(ProviderMode.REAL if row.token_source == "actual" else ProviderMode.MOCK),
        model=row.provider_model,
        prompt_hash=row.prompt_hash,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        reasoning_tokens=None,
        latency_ms=max(0, round(row.latency_ms)),
        first_token_ms=None,
    )


def _fts_candidate_ids(
    session: Session,
    *,
    owner_id: str,
    current_turn: str,
    limit: int,
) -> list[str]:
    tokens = _SAFE_FTS_TOKEN.findall(current_turn.casefold())[:12]
    if not tokens:
        return []
    expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
    rows = session.execute(
        text(
            "SELECT memory_id FROM memory_cards_fts "
            "WHERE owner_id = :owner_id AND memory_cards_fts MATCH :query "
            "ORDER BY bm25(memory_cards_fts), memory_id LIMIT :limit"
        ),
        {"owner_id": owner_id, "query": expression, "limit": limit},
    ).all()
    return [str(row[0]) for row in rows]
