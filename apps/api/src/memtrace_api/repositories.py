"""Data repositories with UserContext owner isolation for G1 persistence."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from memtrace_api.db_models import (
    AgentRunModel,
    DemoSessionModel,
    EventLogModel,
    FeedbackEventModel,
    IdempotencyKeyModel,
    ImportBatchModel,
    MemoryCardModel,
    MemoryEvidenceLinkModel,
    MemoryEvidenceModel,
    MemoryJobModel,
    MemoryRelationModel,
    MemoryUsageModel,
    MemoryVerificationJobModel,
    MemoryVersionModel,
    MessageModel,
    RetrievalDecisionModel,
    RetrievalTraceModel,
    TaskFingerprintModel,
    TaskModel,
    ToolCallModel,
    UserModel,
)
from memtrace_api.events import EventType
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.schemas import (
    AsyncErrorCode,
    CreatedByAction,
    Domain,
    EffectiveMemoryMode,
    FeedbackEventRecord,
    FeedbackType,
    MessageRole,
    MessageSnapshot,
    ProviderMode,
    RunErrorSnapshot,
    RunStatus,
    Scenario,
    TaskCreateRequest,
    TaskFingerprint,
    TaskMessageRecord,
    TaskSnapshot,
    ToolCallSnapshot,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    demo_alias: str
    session_id: str | None = None
    session_expires_at: datetime | None = None


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: str) -> UserModel | None:
        return self.session.execute(
            select(UserModel).where(UserModel.id == user_id)
        ).scalar_one_or_none()

    def get_by_alias(self, demo_alias: str) -> UserModel | None:
        return self.session.execute(
            select(UserModel).where(UserModel.demo_alias == demo_alias)
        ).scalar_one_or_none()

    def ensure_demo_users(self) -> dict[str, UserModel]:
        """Idempotently ensure blank_demo and seeded_demo exist."""
        result: dict[str, UserModel] = {}
        for alias in ("blank_demo", "seeded_demo"):
            user = self.get_by_alias(alias)
            if user is None:
                user = UserModel(
                    id=new_prefixed_ulid("usr"),
                    demo_alias=alias,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                self.session.add(user)
                self.session.flush()
            result[alias] = user
        return result


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(
        self,
        *,
        owner_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> DemoSessionModel:
        now = utc_now()
        session_obj = DemoSessionModel(
            id=new_prefixed_ulid("sess"),
            owner_id=owner_id,
            token_hash=token_hash,
            expires_at=expires_at,
            created_at=now,
        )
        self.session.add(session_obj)
        self.session.flush()
        return session_obj

    def get_valid_session_user(self, token_hash: str) -> tuple[DemoSessionModel, UserModel] | None:
        now = utc_now()
        row = self.session.execute(
            select(DemoSessionModel, UserModel)
            .join(UserModel, DemoSessionModel.owner_id == UserModel.id)
            .where(
                and_(
                    DemoSessionModel.token_hash == token_hash,
                    DemoSessionModel.revoked_at.is_(None),
                    DemoSessionModel.expires_at > now,
                )
            )
        ).first()
        if row is None:
            return None
        return row[0], row[1]

    def revoke_by_token_hash(self, token_hash: str) -> None:
        self.session.execute(
            update(DemoSessionModel)
            .where(DemoSessionModel.token_hash == token_hash)
            .values(revoked_at=utc_now())
        )


class TaskRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def create_task(
        self,
        *,
        task_id: str,
        run_id: str,
        request: TaskCreateRequest,
        detected_domain: Domain,
        provider_mode: ProviderMode,
        model: str,
    ) -> tuple[TaskModel, AgentRunModel, MessageModel, EventLogModel]:
        now = utc_now()
        task = TaskModel(
            id=task_id,
            owner_id=self.user_ctx.user_id,
            scenario=detected_domain.value,
            task_text=request.task_text,
            effective_memory_mode=request.effective_memory_mode.value,
            status="active",
            next_event_seq=2,  # seq 1 will be task.created
            created_at=now,
            updated_at=now,
        )
        run = AgentRunModel(
            id=run_id,
            owner_id=self.user_ctx.user_id,
            task_id=task_id,
            provider_mode=provider_mode.value,
            model=model,
            status=RunStatus.QUEUED.value,
            stage="queued",
            token_source="mock" if provider_mode == ProviderMode.MOCK else "actual",
            created_at=now,
        )
        user_message = MessageModel(
            id=new_prefixed_ulid("msg"),
            owner_id=self.user_ctx.user_id,
            task_id=task_id,
            run_id=None,
            role=MessageRole.USER.value,
            content=request.task_text,
            created_at=now,
        )
        created_event = EventLogModel(
            id=new_prefixed_ulid("evt"),
            owner_id=self.user_ctx.user_id,
            stream_type="task",
            stream_id=task_id,
            seq=1,
            event_type=EventType.TASK_CREATED.value,
            metadata_json=json.dumps({"task_status": "active", "run_status": "queued"}),
            created_at=now,
        )
        self.session.add_all([task, run, user_message, created_event])
        self.session.flush()
        return task, run, user_message, created_event

    def get_task(self, task_id: str) -> TaskModel | None:
        return self.session.execute(
            select(TaskModel).where(
                and_(
                    TaskModel.id == task_id,
                    TaskModel.owner_id == self.user_ctx.user_id,
                    TaskModel.status != "deleted",
                )
            )
        ).scalar_one_or_none()

    def allocate_next_event_seq(self, task_id: str) -> int:
        """Allocate one sequence with SQLite's single-writer UPDATE semantics."""
        next_value = self.session.execute(
            update(TaskModel)
            .where(
                and_(
                    TaskModel.id == task_id,
                    TaskModel.owner_id == self.user_ctx.user_id,
                )
            )
            .values(
                next_event_seq=TaskModel.next_event_seq + 1,
                updated_at=utc_now(),
            )
            .returning(TaskModel.next_event_seq)
        ).scalar_one_or_none()
        if next_value is None:
            raise ValueError(f"task not found for event seq allocation: {task_id}")
        return next_value - 1

    def append_event(
        self,
        *,
        stream_type: str,
        stream_id: str,
        seq: int,
        event_type: str,
        metadata: dict[str, Any],
    ) -> EventLogModel:
        event = EventLogModel(
            id=new_prefixed_ulid("evt"),
            owner_id=self.user_ctx.user_id,
            stream_type=stream_type,
            stream_id=stream_id,
            seq=seq,
            event_type=event_type,
            metadata_json=json.dumps(metadata, separators=(",", ":"), ensure_ascii=False),
            created_at=utc_now(),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_events_after(
        self,
        *,
        stream_type: str,
        stream_id: str,
        after_event_seq: int,
    ) -> list[EventLogModel]:
        return list(
            self.session.execute(
                select(EventLogModel)
                .where(
                    and_(
                        EventLogModel.owner_id == self.user_ctx.user_id,
                        EventLogModel.stream_type == stream_type,
                        EventLogModel.stream_id == stream_id,
                        EventLogModel.seq > after_event_seq,
                    )
                )
                .order_by(EventLogModel.seq.asc())
            )
            .scalars()
            .all()
        )

    def get_latest_run(self, task_id: str) -> AgentRunModel | None:
        return (
            self.session.execute(
                select(AgentRunModel)
                .where(
                    and_(
                        AgentRunModel.task_id == task_id,
                        AgentRunModel.owner_id == self.user_ctx.user_id,
                    )
                )
                .order_by(AgentRunModel.created_at.desc())
            )
            .scalars()
            .first()
        )

    def get_snapshot(self, task_id: str, *, request_id: str) -> TaskSnapshot | None:
        task = self.get_task(task_id)
        if task is None:
            return None

        run = self.get_latest_run(task_id)
        if run is None:
            return None

        # Fingerprint
        fp_row = self.session.execute(
            select(TaskFingerprintModel).where(
                and_(
                    TaskFingerprintModel.task_id == task_id,
                    TaskFingerprintModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()
        fingerprint = None
        if fp_row is not None:
            fingerprint = TaskFingerprint.model_validate_json(fp_row.fingerprint_json)

        # Tool calls
        tool_call_rows = list(
            self.session.execute(
                select(ToolCallModel)
                .where(
                    and_(
                        ToolCallModel.task_id == task_id,
                        ToolCallModel.run_id == run.id,
                        ToolCallModel.owner_id == self.user_ctx.user_id,
                    )
                )
                .order_by(ToolCallModel.created_at.asc())
            )
            .scalars()
            .all()
        )
        tool_calls: list[ToolCallSnapshot] = []
        for tc in tool_call_rows:
            raw_dict = {
                "tool_call_id": tc.id,
                "tool_name": tc.tool_name,
                "reason": tc.reason,
                "args_summary": json.loads(tc.args_summary_json),
                "status": tc.status,
                "latency_ms": tc.duration_ms,
                "result_ref": tc.result_ref,
                "result": json.loads(tc.result_summary_json) if tc.result_summary_json else None,
            }
            tool_calls.append(ToolCallSnapshot.model_validate(raw_dict))

        # Messages
        message_rows = list(
            self.session.execute(
                select(MessageModel)
                .where(
                    and_(
                        MessageModel.task_id == task_id,
                        MessageModel.owner_id == self.user_ctx.user_id,
                    )
                )
                .order_by(MessageModel.created_at.asc())
            )
            .scalars()
            .all()
        )
        messages: list[TaskMessageRecord] = [
            TaskMessageRecord(
                message_id=m.id,
                run_id=m.run_id,
                role=MessageRole(m.role),
                content=m.content,
                created_at=m.created_at,
            )
            for m in message_rows
        ]

        # Assistant message for final_message
        assistant_msg = next(
            (
                m
                for m in message_rows
                if m.role == MessageRole.ASSISTANT.value and m.run_id == run.id
            ),
            None,
        )
        final_message = (
            MessageSnapshot(
                id=assistant_msg.id,
                role="assistant",
                content=assistant_msg.content,
                created_at=assistant_msg.created_at,
            )
            if assistant_msg and run.status == RunStatus.SUCCEEDED.value
            else None
        )

        # Feedback events
        feedback_rows = list(
            self.session.execute(
                select(FeedbackEventModel)
                .where(
                    and_(
                        FeedbackEventModel.task_id == task_id,
                        FeedbackEventModel.owner_id == self.user_ctx.user_id,
                    )
                )
                .order_by(FeedbackEventModel.created_at.asc())
            )
            .scalars()
            .all()
        )
        feedback_events: list[FeedbackEventRecord] = []
        for fb in feedback_rows:
            job_row = self.session.execute(
                select(MemoryJobModel).where(MemoryJobModel.feedback_id == fb.id)
            ).scalar_one_or_none()
            job_id = job_row.id if job_row else new_prefixed_ulid("job")
            feedback_events.append(
                FeedbackEventRecord(
                    feedback_id=fb.id,
                    run_id=fb.run_id,
                    feedback_type=FeedbackType(fb.feedback_type),
                    explicit_text=fb.explicit_text,
                    edited_output=fb.edited_output,
                    rating=fb.rating,
                    accepted=fb.accepted,
                    memory_job_id=job_id,
                    created_at=fb.created_at,
                )
            )

        # Error
        error_snapshot = None
        if run.status == RunStatus.FAILED.value and run.error_code:
            error_snapshot = RunErrorSnapshot(
                error_id=new_prefixed_ulid("err"),
                code=AsyncErrorCode(run.error_code),
                message="运行失败或在进程重启时被中断。",
                retryable=False,
            )

        # Output text
        output_text = assistant_msg.content if assistant_msg else ""
        end_offset = len(output_text.encode("utf-8"))

        terminal = run.status in (RunStatus.SUCCEEDED.value, RunStatus.FAILED.value)

        from memtrace_api.g3_service import load_task_g3

        retrieval_trace, memory_usages = load_task_g3(
            self.session,
            self.user_ctx,
            request_id=request_id,
            task_id=task_id,
            run_id=run.id,
        )

        # Last persistent event seq
        max_seq = self.session.execute(
            select(func.max(EventLogModel.seq)).where(
                and_(
                    EventLogModel.owner_id == self.user_ctx.user_id,
                    EventLogModel.stream_type == "task",
                    EventLogModel.stream_id == task_id,
                )
            )
        ).scalar() or (task.next_event_seq - 1)

        return TaskSnapshot(
            request_id=request_id,
            task_id=task.id,
            run_id=run.id,
            task_text=task.task_text,
            scenario=Scenario(task.scenario),
            task_status="active",
            run_status=RunStatus(run.status),
            provider_mode=ProviderMode(run.provider_mode),
            effective_memory_mode=EffectiveMemoryMode(task.effective_memory_mode),
            fingerprint=fingerprint,
            public_plan=None,
            tool_decision=None,
            tool_calls=tool_calls,
            partial_output=output_text,
            end_offset=end_offset,
            offset_unit="utf8_bytes",
            messages=messages,
            final_message=final_message,
            feedback_events=feedback_events,
            retrieval_trace=retrieval_trace,
            memory_usages=memory_usages,
            error=error_snapshot,
            terminal=terminal,
            last_persistent_event_seq=max_seq,
            updated_at=task.updated_at,
        )

    def cleanup_interrupted_runs(self) -> int:
        """Mark active/non-terminal runs as FAILED with RUN_INTERRUPTED on restart."""
        active_statuses = [
            RunStatus.QUEUED.value,
            RunStatus.FINGERPRINTING.value,
            RunStatus.RETRIEVING.value,
            RunStatus.PLANNING.value,
            RunStatus.TOOL_RUNNING.value,
            RunStatus.GENERATING.value,
        ]
        stmt = (
            update(AgentRunModel)
            .where(AgentRunModel.status.in_(active_statuses))
            .values(
                status=RunStatus.FAILED.value,
                stage="failed",
                error_code=AsyncErrorCode.RUN_INTERRUPTED.value,
                completed_at=utc_now(),
            )
        )
        res = self.session.execute(stmt)
        return res.rowcount


class FeedbackRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def record_feedback(
        self,
        *,
        task_id: str,
        run_id: str,
        feedback_id: str,
        job_id: str,
        feedback_type: FeedbackType,
        explicit_text: str | None,
        edited_output: str | None,
        rating: int | None,
        accepted: bool | None,
    ) -> tuple[FeedbackEventModel, MemoryJobModel, EventLogModel]:
        now = utc_now()
        fb = FeedbackEventModel(
            id=feedback_id,
            owner_id=self.user_ctx.user_id,
            task_id=task_id,
            run_id=run_id,
            feedback_type=feedback_type.value,
            explicit_text=explicit_text,
            edited_output=edited_output,
            rating=rating,
            accepted=accepted,
            created_at=now,
        )
        job = MemoryJobModel(
            id=job_id,
            owner_id=self.user_ctx.user_id,
            job_type="extract_feedback",
            feedback_id=feedback_id,
            status="pending",
            stage="queued",
            attempt=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add_all([fb, job])
        self.session.flush()

        # Allocate seq
        task_repo = TaskRepository(self.user_ctx, self.session)
        seq = task_repo.allocate_next_event_seq(task_id)

        # Append metadata-only event to event_log
        event = task_repo.append_event(
            stream_type="task",
            stream_id=task_id,
            seq=seq,
            event_type=EventType.FEEDBACK_RECORDED.value,
            metadata={
                "feedback_id": feedback_id,
                "memory_job_id": job_id,
                "feedback_type": feedback_type.value,
            },
        )
        return fb, job, event

    def get_feedback(self, feedback_id: str) -> FeedbackEventModel | None:
        return self.session.execute(
            select(FeedbackEventModel).where(
                and_(
                    FeedbackEventModel.id == feedback_id,
                    FeedbackEventModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()


class MemoryJobRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def get_memory_job(self, job_id: str) -> MemoryJobModel | None:
        return self.session.execute(
            select(MemoryJobModel).where(
                and_(
                    MemoryJobModel.id == job_id,
                    MemoryJobModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()

    def list_candidate_ids(self, job_id: str) -> list[str]:
        return list(
            self.session.execute(
                select(MemoryCardModel.id)
                .join(
                    MemoryEvidenceLinkModel,
                    MemoryEvidenceLinkModel.memory_id == MemoryCardModel.id,
                )
                .where(
                    and_(
                        MemoryCardModel.memory_job_id == job_id,
                        MemoryCardModel.owner_id == self.user_ctx.user_id,
                        MemoryEvidenceLinkModel.owner_id == self.user_ctx.user_id,
                    )
                )
                .order_by(MemoryEvidenceLinkModel.ordinal.asc(), MemoryCardModel.id.asc())
                .limit(3)
            ).scalars()
        )

    def update_stage(self, job_id: str, stage: str) -> None:
        self.session.execute(
            update(MemoryJobModel)
            .where(
                and_(
                    MemoryJobModel.id == job_id,
                    MemoryJobModel.owner_id == self.user_ctx.user_id,
                )
            )
            .values(stage=stage, updated_at=utc_now())
        )

    def complete_job(
        self,
        *,
        job_id: str,
        disposition: str,
        candidate_ids: list[str],
    ) -> None:
        self.session.execute(
            update(MemoryJobModel)
            .where(
                and_(
                    MemoryJobModel.id == job_id,
                    MemoryJobModel.owner_id == self.user_ctx.user_id,
                )
            )
            .values(
                status="completed",
                stage="done",
                disposition=disposition,
                retryable=False,
                last_error_code=None,
                updated_at=utc_now(),
            )
        )

    def fail_job(
        self,
        *,
        job_id: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        self.session.execute(
            update(MemoryJobModel)
            .where(
                and_(
                    MemoryJobModel.id == job_id,
                    MemoryJobModel.owner_id == self.user_ctx.user_id,
                )
            )
            .values(
                status="failed",
                stage="failed",
                last_error_code=error_code,
                retryable=retryable,
                updated_at=utc_now(),
            )
        )


class MemoryCardRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def get_candidate(self, memory_id: str) -> MemoryCardModel | None:
        return self.session.execute(
            select(MemoryCardModel).where(
                and_(
                    MemoryCardModel.id == memory_id,
                    MemoryCardModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()

    def update_card(self, card_id: str, **updates: Any) -> None:
        self.session.execute(
            update(MemoryCardModel)
            .where(
                and_(
                    MemoryCardModel.id == card_id,
                    MemoryCardModel.owner_id == self.user_ctx.user_id,
                )
            )
            .values(**updates)
        )

    def create_version(self, card_id: str, version: int, created_by_action: str) -> str:
        from memtrace_api.ids import new_prefixed_ulid

        card = self.get_candidate(card_id)
        if card is None:
            raise ValueError(f"Card {card_id} not found")

        version_id = new_prefixed_ulid("memver")
        ver = MemoryVersionModel(
            id=version_id,
            owner_id=self.user_ctx.user_id,
            memory_id=card_id,
            version=version,
            title=card.title,
            rule=card.rule,
            avoid=card.avoid,
            trigger_text=card.trigger_text,
            scope_json=card.scope_json,
            exceptions_json=card.exceptions_json,
            created_by_action=created_by_action,
            created_at=utc_now(),
        )
        self.session.add(ver)
        self.session.flush()
        return version_id

    def list_evidence(self, memory_id: str) -> list[MemoryEvidenceModel]:
        result = self.session.execute(
            select(MemoryEvidenceModel)
            .join(
                MemoryEvidenceLinkModel,
                MemoryEvidenceModel.id == MemoryEvidenceLinkModel.evidence_id,
            )
            .where(
                and_(
                    MemoryEvidenceLinkModel.memory_id == memory_id,
                    MemoryEvidenceLinkModel.owner_id == self.user_ctx.user_id,
                    MemoryEvidenceModel.owner_id == self.user_ctx.user_id,
                )
            )
            .order_by(MemoryEvidenceLinkModel.ordinal)
        )
        return list(result.scalars().all())

    def list_versions(self, memory_id: str) -> list[MemoryVersionModel]:
        result = self.session.execute(
            select(MemoryVersionModel)
            .where(
                and_(
                    MemoryVersionModel.memory_id == memory_id,
                    MemoryVersionModel.owner_id == self.user_ctx.user_id,
                )
            )
            .order_by(MemoryVersionModel.version)
        )
        return list(result.scalars().all())

    def list_cards(
        self,
        *,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> list[MemoryCardModel]:
        q = select(MemoryCardModel).where(MemoryCardModel.owner_id == self.user_ctx.user_id)
        if status:
            q = q.where(MemoryCardModel.status == status)
        if cursor:
            q = q.where(MemoryCardModel.id < cursor)
        q = q.order_by(MemoryCardModel.id.desc()).limit(limit)
        result = self.session.execute(q)
        return list(result.scalars().all())


class IdempotencyRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def get_record(self, route: str, key: str) -> IdempotencyKeyModel | None:
        now = utc_now()
        self.session.execute(
            IdempotencyKeyModel.__table__.delete().where(
                and_(
                    IdempotencyKeyModel.owner_id == self.user_ctx.user_id,
                    IdempotencyKeyModel.route == route,
                    IdempotencyKeyModel.key == key,
                    IdempotencyKeyModel.expires_at <= now,
                )
            )
        )
        return self.session.execute(
            select(IdempotencyKeyModel).where(
                and_(
                    IdempotencyKeyModel.owner_id == self.user_ctx.user_id,
                    IdempotencyKeyModel.route == route,
                    IdempotencyKeyModel.key == key,
                    IdempotencyKeyModel.expires_at > now,
                )
            )
        ).scalar_one_or_none()

    def save_record(
        self,
        *,
        route: str,
        key: str,
        request_hash: str,
        response_status: int,
        response_json: str,
        expires_at: datetime,
    ) -> IdempotencyKeyModel:
        record = IdempotencyKeyModel(
            id=new_prefixed_ulid("idem"),
            owner_id=self.user_ctx.user_id,
            route=route,
            key=key,
            request_hash=request_hash,
            response_status=response_status,
            response_json=response_json,
            expires_at=expires_at,
            created_at=utc_now(),
        )
        self.session.add(record)
        self.session.flush()
        return record


# ===========================================================================
# Day 4 G3 retrieval and memory lifecycle repositories
# ===========================================================================


class RetrievalRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def save_trace(
        self, trace: RetrievalTraceModel, decisions: list[RetrievalDecisionModel]
    ) -> None:
        self.session.add(trace)
        for d in decisions:
            self.session.add(d)

    def get_trace(self, trace_id: str) -> RetrievalTraceModel | None:
        return self.session.execute(
            select(RetrievalTraceModel).where(
                and_(
                    RetrievalTraceModel.id == trace_id,
                    RetrievalTraceModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()

    def get_trace_by_run(self, task_id: str, run_id: str) -> RetrievalTraceModel | None:
        return self.session.execute(
            select(RetrievalTraceModel).where(
                and_(
                    RetrievalTraceModel.task_id == task_id,
                    RetrievalTraceModel.run_id == run_id,
                    RetrievalTraceModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()

    def list_decisions(self, trace_id: str) -> list[RetrievalDecisionModel]:
        return list(
            self.session.execute(
                select(RetrievalDecisionModel)
                .where(
                    and_(
                        RetrievalDecisionModel.retrieval_trace_id == trace_id,
                        RetrievalDecisionModel.owner_id == self.user_ctx.user_id,
                    )
                )
                .order_by(RetrievalDecisionModel.id.asc())
            )
            .scalars()
            .all()
        )


class MemoryUsageRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def save_usages(self, usages: list[MemoryUsageModel]) -> None:
        for u in usages:
            self.session.add(u)

    def list_by_run(self, task_id: str, run_id: str) -> list[MemoryUsageModel]:
        return list(
            self.session.execute(
                select(MemoryUsageModel)
                .where(
                    and_(
                        MemoryUsageModel.task_id == task_id,
                        MemoryUsageModel.run_id == run_id,
                        MemoryUsageModel.owner_id == self.user_ctx.user_id,
                    )
                )
                .order_by(MemoryUsageModel.rank.asc(), MemoryUsageModel.id.asc())
            )
            .scalars()
            .all()
        )

    def list_by_memory(
        self, memory_id: str, cursor: str | None = None, limit: int = 50
    ) -> list[MemoryUsageModel]:
        q = select(MemoryUsageModel).where(
            and_(
                MemoryUsageModel.memory_id == memory_id,
                MemoryUsageModel.owner_id == self.user_ctx.user_id,
            )
        )
        if cursor:
            q = q.where(MemoryUsageModel.id < cursor)
        q = q.order_by(MemoryUsageModel.id.desc()).limit(limit)
        return list(self.session.execute(q).scalars().all())

    def get_usage(self, task_id: str, run_id: str, memory_id: str) -> MemoryUsageModel | None:
        return self.session.execute(
            select(MemoryUsageModel).where(
                and_(
                    MemoryUsageModel.task_id == task_id,
                    MemoryUsageModel.run_id == run_id,
                    MemoryUsageModel.memory_id == memory_id,
                    MemoryUsageModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()

    def update_user_effect(self, usage_id: str, effect: str) -> MemoryUsageModel | None:
        row = self.session.execute(
            select(MemoryUsageModel).where(
                and_(
                    MemoryUsageModel.id == usage_id,
                    MemoryUsageModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.user_effect = effect
        row.updated_at = utc_now()
        return row

    def update_verification(
        self, usage_id: str, status: str, method: str | None, excerpt: str | None
    ) -> MemoryUsageModel | None:
        row = self.session.execute(
            select(MemoryUsageModel).where(
                and_(
                    MemoryUsageModel.id == usage_id,
                    MemoryUsageModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.verification_status = status
        row.verification_method = method
        if excerpt is not None:
            row.evidence_excerpt = excerpt[:120]
        row.updated_at = utc_now()
        return row


# ===========================================================================
# Day 5 G4: Memory Center / Conflict / Pack / Import G4 helpers & repos
# ===========================================================================


def _nfkc_cf(s: str) -> str:
    import unicodedata as _ud

    return _ud.normalize("NFKC", s).casefold()


def _collapse_ws(s: str) -> str:
    return " ".join(s.split())


def _query_token(s: str) -> str:
    return _collapse_ws(_nfkc_cf(s))


def _nfkc_contains(haystack: str, needle: str) -> bool:
    return _query_token(needle) in _query_token(haystack)


def _rfc8785_canonical_bytes(data: dict[str, Any]) -> bytes:
    """RFC 8785 JSON Canonicalization Scheme.

    Uses rfc8785 library for proper JCS, not simple sort_keys.
    """
    import rfc8785

    return rfc8785.dumps(data)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clear_idempotency_snapshots(session: Session, user_id: str, resource_ids: list[str]) -> None:
    for rid in resource_ids:
        session.execute(
            IdempotencyKeyModel.__table__.delete().where(
                and_(
                    IdempotencyKeyModel.owner_id == user_id,
                    IdempotencyKeyModel.response_json.like(f"%{rid}%"),
                )
            )
        )


# ── G4 MemoryCard (extended, separate class to not break G1-G3 routes) ─────


class MemoryCardG4Repository(MemoryCardRepository):
    """G4 Memory Center lifecycle operations."""

    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        super().__init__(user_ctx, session)

    def _q(self) -> Any:
        return and_(
            MemoryCardModel.owner_id == self.user_ctx.user_id,
            MemoryCardModel.status != "deleted",
        )

    def _get(self, memory_id: str) -> MemoryCardModel | None:
        return self.session.execute(
            select(MemoryCardModel).where(and_(MemoryCardModel.id == memory_id, self._q()))
        ).scalar_one_or_none()

    def _update(self, card_id: str, **updates: Any) -> None:
        self.session.execute(
            update(MemoryCardModel)
            .where(
                and_(
                    MemoryCardModel.id == card_id,
                    MemoryCardModel.owner_id == self.user_ctx.user_id,
                )
            )
            .values(**updates)
        )

    # ── G4 list with full filters ──────────────────────────────────────────

    def list_memories(
        self,
        *,
        query: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        domain: str | None = None,
        task_type: str | None = None,
        source_type: str | None = None,
        used_after: datetime | None = None,
        sort: str = "updated_desc",
        cursor_value: datetime | str | None = None,
        cursor_id: str | None = None,
        limit: int = 51,
    ) -> list[MemoryCardModel]:
        q = select(MemoryCardModel).where(self._q())
        if status:
            q = q.where(MemoryCardModel.status == status)
        if kind:
            q = q.where(MemoryCardModel.kind == kind)
        if domain:
            q = q.where(MemoryCardModel.domain == domain)
        if task_type:
            q = q.where(MemoryCardModel.task_type == task_type)
        if source_type:
            q = q.where(MemoryCardModel.source_type == source_type)
        if used_after is not None:
            q = q.where(MemoryCardModel.last_used_at >= used_after)
        if query:
            norm = _query_token(query)
            pattern = f"%{norm}%"
            q = q.where(
                or_(
                    func.memtrace_nfkc_cf(MemoryCardModel.title).like(pattern),
                    func.memtrace_nfkc_cf(MemoryCardModel.rule).like(pattern),
                    func.memtrace_nfkc_cf(MemoryCardModel.trigger_text).like(pattern),
                )
            )
        sort_column = {
            "updated_desc": MemoryCardModel.updated_at,
            "created_desc": MemoryCardModel.created_at,
            "last_used_desc": MemoryCardModel.last_used_at,
            "title_asc": MemoryCardModel.title,
        }[sort]
        if cursor_id is not None:
            if sort == "title_asc":
                assert isinstance(cursor_value, str)
                q = q.where(
                    or_(
                        sort_column > cursor_value,
                        and_(sort_column == cursor_value, MemoryCardModel.id > cursor_id),
                    )
                )
            elif sort == "last_used_desc":
                if cursor_value is None:
                    q = q.where(and_(sort_column.is_(None), MemoryCardModel.id > cursor_id))
                else:
                    q = q.where(
                        or_(
                            sort_column < cursor_value,
                            sort_column.is_(None),
                            and_(sort_column == cursor_value, MemoryCardModel.id > cursor_id),
                        )
                    )
            else:
                assert isinstance(cursor_value, datetime)
                q = q.where(
                    or_(
                        sort_column < cursor_value,
                        and_(sort_column == cursor_value, MemoryCardModel.id > cursor_id),
                    )
                )
        direction = sort_column.asc() if sort == "title_asc" else sort_column.desc()
        q = q.order_by(direction, MemoryCardModel.id.asc()).limit(limit)
        return list(self.session.execute(q).scalars().all())

    # ── G4 detail / versions / usages / relations ──────────────────────────

    def get_detail(self, memory_id: str) -> MemoryCardModel | None:
        return self._get(memory_id)

    def list_relations(self, memory_id: str) -> list[MemoryRelationModel]:
        return list(
            self.session.execute(
                select(MemoryRelationModel)
                .where(
                    and_(
                        MemoryRelationModel.owner_id == self.user_ctx.user_id,
                        MemoryRelationModel.from_memory_id == memory_id,
                    )
                )
                .order_by(MemoryRelationModel.created_at.desc())
            )
            .scalars()
            .all()
        )

    def list_usages_for_memory(
        self, memory_id: str, cursor: str | None = None, limit: int = 51
    ) -> list[MemoryUsageModel]:
        q = select(MemoryUsageModel).where(
            and_(
                MemoryUsageModel.memory_id == memory_id,
                MemoryUsageModel.owner_id == self.user_ctx.user_id,
            )
        )
        if cursor:
            q = q.where(MemoryUsageModel.id < cursor)
        q = q.order_by(MemoryUsageModel.id.desc()).limit(limit)
        return list(self.session.execute(q).scalars().all())

    # ── G4 lifecycle ───────────────────────────────────────────────────────

    def edit(
        self,
        memory_id: str,
        expected_version_id: str,
        *,
        title: str,
        rule: str,
        avoid: str,
        scope_json: str,
        exceptions_json: str,
        trigger_text: str | None = None,
    ) -> tuple[MemoryCardModel, str]:
        card = self._get(memory_id)
        if card is None:
            raise ValueError("MEMORY_NOT_FOUND")
        if card.current_version_id != expected_version_id:
            raise ValueError("MEMORY_VERSION_CONFLICT")
        allowed = {"active", "paused", "archived", "conflicted"}
        if card.status not in allowed:
            raise ValueError(f"MEMORY_STATE_CONFLICT: cannot edit {card.status}")
        next_ver = card.version + 1
        version_id = new_prefixed_ulid("memver")
        now = utc_now()
        eff_trigger = card.trigger_text if trigger_text is None else trigger_text
        self.session.add(
            MemoryVersionModel(
                id=version_id,
                owner_id=self.user_ctx.user_id,
                memory_id=memory_id,
                version=next_ver,
                title=title,
                rule=rule,
                avoid=avoid,
                trigger_text=eff_trigger,
                scope_json=scope_json,
                exceptions_json=exceptions_json,
                created_by_action=CreatedByAction.EDIT.value,
                created_at=now,
            )
        )
        self._update(
            memory_id,
            title=title,
            rule=rule,
            avoid=avoid,
            trigger_text=eff_trigger,
            scope_json=scope_json,
            exceptions_json=exceptions_json,
            current_version_id=version_id,
            version=next_ver,
            updated_at=now,
        )
        self.session.flush()
        updated = self._get(memory_id)
        assert updated is not None
        return updated, version_id

    def set_status(
        self, memory_id: str, expected_version_id: str, new_status: str
    ) -> MemoryCardModel:
        card = self._get(memory_id)
        if card is None:
            raise ValueError("MEMORY_NOT_FOUND")
        if card.current_version_id != expected_version_id:
            raise ValueError("MEMORY_VERSION_CONFLICT")
        self._update(memory_id, status=new_status, updated_at=utc_now())
        self.session.flush()
        updated = self._get(memory_id)
        assert updated is not None
        return updated

    # ── permanent delete ──────────────────────────────────────────────────

    def permanent_delete(
        self,
        memory_id: str,
        expected_version_id: str | None,
        confirm_title: str,
    ) -> dict[str, Any]:
        card = self._get(memory_id)
        if card is None:
            raise ValueError("MEMORY_NOT_FOUND")
        if card.current_version_id != expected_version_id:
            raise ValueError("MEMORY_VERSION_CONFLICT")
        if card.title != confirm_title:
            raise ValueError("CONFIRMATION_MISMATCH")
        now = utc_now()
        linked_ids = [
            link.evidence_id
            for link in self.session.execute(
                select(MemoryEvidenceLinkModel).where(
                    MemoryEvidenceLinkModel.memory_id == memory_id
                )
            )
            .scalars()
            .all()
        ]
        version_ids = list(
            self.session.execute(
                select(MemoryVersionModel.id).where(
                    and_(
                        MemoryVersionModel.owner_id == self.user_ctx.user_id,
                        MemoryVersionModel.memory_id == memory_id,
                    )
                )
            ).scalars()
        )
        usage_ids = list(
            self.session.execute(
                select(MemoryUsageModel.id).where(
                    and_(
                        MemoryUsageModel.owner_id == self.user_ctx.user_id,
                        MemoryUsageModel.memory_id == memory_id,
                    )
                )
            ).scalars()
        )
        if usage_ids:
            self.session.execute(
                MemoryVerificationJobModel.__table__.delete().where(
                    and_(
                        MemoryVerificationJobModel.owner_id == self.user_ctx.user_id,
                        MemoryVerificationJobModel.memory_usage_id.in_(usage_ids),
                    )
                )
            )
        self.session.execute(
            MemoryUsageModel.__table__.delete().where(
                and_(
                    MemoryUsageModel.owner_id == self.user_ctx.user_id,
                    MemoryUsageModel.memory_id == memory_id,
                )
            )
        )
        self.session.execute(
            RetrievalDecisionModel.__table__.delete().where(
                and_(
                    RetrievalDecisionModel.owner_id == self.user_ctx.user_id,
                    RetrievalDecisionModel.memory_id == memory_id,
                )
            )
        )
        self.session.execute(
            MemoryRelationModel.__table__.delete().where(
                and_(
                    MemoryRelationModel.owner_id == self.user_ctx.user_id,
                    or_(
                        MemoryRelationModel.from_memory_id == memory_id,
                        MemoryRelationModel.to_memory_id == memory_id,
                        MemoryRelationModel.resolution_memory_id == memory_id,
                    ),
                )
            )
        )
        self.session.execute(
            MemoryVersionModel.__table__.delete().where(
                and_(
                    MemoryVersionModel.owner_id == self.user_ctx.user_id,
                    MemoryVersionModel.memory_id == memory_id,
                )
            )
        )
        self.session.execute(
            MemoryEvidenceLinkModel.__table__.delete().where(
                and_(
                    MemoryEvidenceLinkModel.owner_id == self.user_ctx.user_id,
                    MemoryEvidenceLinkModel.memory_id == memory_id,
                )
            )
        )
        for eid in linked_ids:
            remaining = self.session.execute(
                select(MemoryEvidenceLinkModel.id).where(MemoryEvidenceLinkModel.evidence_id == eid)
            ).scalar_one_or_none()
            if remaining is None:
                self.session.execute(
                    MemoryEvidenceModel.__table__.delete().where(
                        and_(
                            MemoryEvidenceModel.id == eid,
                            MemoryEvidenceModel.owner_id == self.user_ctx.user_id,
                        )
                    )
                )
        resource_ids = [memory_id, *version_ids, *usage_ids, *linked_ids]
        _clear_idempotency_snapshots(self.session, self.user_ctx.user_id, resource_ids)
        self.session.execute(
            update(ImportBatchModel)
            .where(
                and_(
                    ImportBatchModel.owner_id == self.user_ctx.user_id,
                    ImportBatchModel.status == "quarantined",
                    or_(
                        ImportBatchModel.canonical_payload_json.like(f"%{memory_id}%"),
                        ImportBatchModel.preview_json.like(f"%{memory_id}%"),
                    ),
                )
            )
            .values(
                status="cancelled",
                canonical_payload_json=None,
                preview_json=None,
                preview_token_hash=None,
                error_message="RESOURCE_DELETED",
                updated_at=now,
            )
        )
        self._update(
            memory_id,
            status="deleted",
            kind=None,
            title=None,
            rule=None,
            avoid=None,
            trigger_text=None,
            scope_level=None,
            domain=None,
            task_type=None,
            artifact_type=None,
            audience=None,
            project_key=None,
            scope_json=None,
            exceptions_json=None,
            source_type=None,
            save_preselected=False,
            rejection_reason=None,
            source_trust=None,
            rule_confidence=None,
            scope_confidence=None,
            evidence_count=0,
            version=0,
            current_version_id=None,
            valid_from=None,
            valid_to=None,
            retrieved_count=0,
            injected_count=0,
            verified_applied_count=0,
            helpful_count=0,
            harmful_count=0,
            stale_count=0,
            last_used_at=None,
            evidence_missing=False,
            deleted_at=now,
            import_batch_id=None,
            import_source_version=None,
            updated_at=now,
        )
        self.session.flush()
        return {"memory_id": memory_id, "status": "deleted", "deleted_at": now}

    # ── source task delete ──────────────────────────────────────────────────

    def delete_source_task(self, task_id: str) -> dict[str, Any]:
        task = self.session.execute(
            select(TaskModel).where(
                and_(
                    TaskModel.id == task_id,
                    TaskModel.owner_id == self.user_ctx.user_id,
                    TaskModel.status != "deleted",
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise ValueError("TASK_NOT_FOUND")
        evidence_ids = list(
            self.session.execute(
                select(MemoryEvidenceModel.id).where(
                    and_(
                        MemoryEvidenceModel.owner_id == self.user_ctx.user_id,
                        MemoryEvidenceModel.task_id == task_id,
                    )
                )
            ).scalars()
        )
        affected_card_ids: list[str] = []
        if evidence_ids:
            affected_card_ids = list(
                self.session.execute(
                    select(MemoryEvidenceLinkModel.memory_id)
                    .where(
                        and_(
                            MemoryEvidenceLinkModel.owner_id == self.user_ctx.user_id,
                            MemoryEvidenceLinkModel.evidence_id.in_(evidence_ids),
                        )
                    )
                    .distinct()
                ).scalars()
            )
        run_ids = list(
            self.session.execute(
                select(AgentRunModel.id).where(
                    and_(
                        AgentRunModel.owner_id == self.user_ctx.user_id,
                        AgentRunModel.task_id == task_id,
                    )
                )
            ).scalars()
        )
        feedback_ids = list(
            self.session.execute(
                select(FeedbackEventModel.id).where(
                    and_(
                        FeedbackEventModel.owner_id == self.user_ctx.user_id,
                        FeedbackEventModel.task_id == task_id,
                    )
                )
            ).scalars()
        )
        job_ids: list[str] = []
        if feedback_ids:
            job_ids = list(
                self.session.execute(
                    select(MemoryJobModel.id).where(
                        and_(
                            MemoryJobModel.owner_id == self.user_ctx.user_id,
                            MemoryJobModel.feedback_id.in_(feedback_ids),
                        )
                    )
                ).scalars()
            )
        usage_ids = list(
            self.session.execute(
                select(MemoryUsageModel.id).where(
                    and_(
                        MemoryUsageModel.owner_id == self.user_ctx.user_id,
                        MemoryUsageModel.task_id == task_id,
                    )
                )
            ).scalars()
        )
        trace_ids = list(
            self.session.execute(
                select(RetrievalTraceModel.id).where(
                    and_(
                        RetrievalTraceModel.owner_id == self.user_ctx.user_id,
                        RetrievalTraceModel.task_id == task_id,
                    )
                )
            ).scalars()
        )
        if usage_ids:
            self.session.execute(
                MemoryVerificationJobModel.__table__.delete().where(
                    and_(
                        MemoryVerificationJobModel.owner_id == self.user_ctx.user_id,
                        MemoryVerificationJobModel.memory_usage_id.in_(usage_ids),
                    )
                )
            )
        self.session.execute(
            MemoryUsageModel.__table__.delete().where(
                and_(
                    MemoryUsageModel.owner_id == self.user_ctx.user_id,
                    MemoryUsageModel.task_id == task_id,
                )
            )
        )
        if trace_ids:
            self.session.execute(
                RetrievalDecisionModel.__table__.delete().where(
                    and_(
                        RetrievalDecisionModel.owner_id == self.user_ctx.user_id,
                        RetrievalDecisionModel.retrieval_trace_id.in_(trace_ids),
                    )
                )
            )
            self.session.execute(
                RetrievalTraceModel.__table__.delete().where(
                    and_(
                        RetrievalTraceModel.owner_id == self.user_ctx.user_id,
                        RetrievalTraceModel.id.in_(trace_ids),
                    )
                )
            )
        if evidence_ids:
            self.session.execute(
                MemoryEvidenceLinkModel.__table__.delete().where(
                    and_(
                        MemoryEvidenceLinkModel.owner_id == self.user_ctx.user_id,
                        MemoryEvidenceLinkModel.evidence_id.in_(evidence_ids),
                    )
                )
            )
            self.session.execute(
                MemoryEvidenceModel.__table__.delete().where(
                    and_(
                        MemoryEvidenceModel.owner_id == self.user_ctx.user_id,
                        MemoryEvidenceModel.id.in_(evidence_ids),
                    )
                )
            )
        if job_ids:
            self.session.execute(
                update(MemoryCardModel)
                .where(
                    and_(
                        MemoryCardModel.owner_id == self.user_ctx.user_id,
                        MemoryCardModel.memory_job_id.in_(job_ids),
                    )
                )
                .values(memory_job_id=None, evidence_missing=True)
            )
            self.session.execute(
                MemoryJobModel.__table__.delete().where(
                    and_(
                        MemoryJobModel.owner_id == self.user_ctx.user_id,
                        MemoryJobModel.id.in_(job_ids),
                    )
                )
            )
        self.session.execute(
            FeedbackEventModel.__table__.delete().where(
                and_(
                    FeedbackEventModel.owner_id == self.user_ctx.user_id,
                    FeedbackEventModel.task_id == task_id,
                )
            )
        )
        for table_model in (MessageModel, ToolCallModel, TaskFingerprintModel):
            self.session.execute(
                table_model.__table__.delete().where(
                    and_(
                        table_model.owner_id == self.user_ctx.user_id,
                        table_model.task_id == task_id,
                    )
                )
            )
        for card_id in affected_card_ids:
            remaining_count = self.session.execute(
                select(func.count(MemoryEvidenceLinkModel.id)).where(
                    and_(
                        MemoryEvidenceLinkModel.owner_id == self.user_ctx.user_id,
                        MemoryEvidenceLinkModel.memory_id == card_id,
                    )
                )
            ).scalar_one()
            self.session.execute(
                update(MemoryCardModel)
                .where(
                    and_(
                        MemoryCardModel.id == card_id,
                        MemoryCardModel.owner_id == self.user_ctx.user_id,
                        MemoryCardModel.status != "deleted",
                    )
                )
                .values(evidence_count=remaining_count, evidence_missing=True, updated_at=utc_now())
            )
        _clear_idempotency_snapshots(
            self.session,
            self.user_ctx.user_id,
            [
                task_id,
                *run_ids,
                *feedback_ids,
                *job_ids,
                *evidence_ids,
                *usage_ids,
                *trace_ids,
                *affected_card_ids,
            ],
        )
        now = utc_now()
        self.session.execute(
            update(TaskModel)
            .where(
                and_(
                    TaskModel.id == task_id,
                    TaskModel.owner_id == self.user_ctx.user_id,
                )
            )
            .values(
                status="deleted",
                task_text="",
                deleted_at=now,
                deleted_by="owner",
                deletion_reason="source_task_delete",
                updated_at=now,
            )
        )
        self.session.flush()
        return {
            "task_id": task_id,
            "affected_card_count": len(affected_card_ids),
            "evidence_missing_cards": len(affected_card_ids),
        }


# ── MemoryRelationRepository ────────────────────────────────────────────────


class MemoryRelationRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def create_relation(
        self,
        *,
        relation_id: str,
        from_memory_id: str,
        to_memory_id: str,
        relation_type: str,
        status: str = "resolved",
        resolution_action: str | None = None,
        resolution_memory_id: str | None = None,
    ) -> MemoryRelationModel:
        referenced_ids = {from_memory_id, to_memory_id}
        if resolution_memory_id is not None:
            referenced_ids.add(resolution_memory_id)
        owned_ids = set(
            self.session.execute(
                select(MemoryCardModel.id).where(
                    and_(
                        MemoryCardModel.owner_id == self.user_ctx.user_id,
                        MemoryCardModel.id.in_(referenced_ids),
                        MemoryCardModel.status != "deleted",
                    )
                )
            ).scalars()
        )
        if owned_ids != referenced_ids or from_memory_id == to_memory_id:
            raise ValueError("MEMORY_NOT_FOUND")
        rel = MemoryRelationModel(
            id=relation_id,
            owner_id=self.user_ctx.user_id,
            from_memory_id=from_memory_id,
            to_memory_id=to_memory_id,
            relation_type=relation_type,
            status=status,
            resolution_action=resolution_action,
            resolution_memory_id=resolution_memory_id,
            resolved_at=utc_now() if status == "resolved" else None,
            created_at=utc_now(),
        )
        self.session.add(rel)
        self.session.flush()
        return rel

    def get(self, relation_id: str) -> MemoryRelationModel | None:
        return self.session.execute(
            select(MemoryRelationModel).where(
                and_(
                    MemoryRelationModel.id == relation_id,
                    MemoryRelationModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()

    def list_relations(
        self,
        memory_id: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
    ) -> list[MemoryRelationModel]:
        q = select(MemoryRelationModel).where(MemoryRelationModel.owner_id == self.user_ctx.user_id)
        if memory_id:
            q = q.where(
                or_(
                    MemoryRelationModel.from_memory_id == memory_id,
                    MemoryRelationModel.to_memory_id == memory_id,
                )
            )
        if status:
            q = q.where(MemoryRelationModel.status == status)
        if cursor:
            q = q.where(MemoryRelationModel.id < cursor)
        q = q.order_by(MemoryRelationModel.created_at.desc()).limit(51)
        return list(self.session.execute(q).scalars().all())

    def resolve(
        self,
        relation_id: str,
        *,
        action: str,
        resolution_memory_id: str | None = None,
    ) -> MemoryRelationModel | None:
        rel = self.get(relation_id)
        if rel is None:
            return None
        rel.status = "resolved"
        rel.resolution_action = action
        rel.resolution_memory_id = resolution_memory_id
        rel.resolved_at = utc_now()
        self.session.flush()
        return rel


# ── ConflictRepository ──────────────────────────────────────────────────────


class ConflictRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def create_conflict(
        self,
        *,
        relation_id: str,
        left_memory_id: str,
        right_memory_id: str,
    ) -> MemoryRelationModel:
        if left_memory_id == right_memory_id:
            raise ValueError("MEMORY_MERGE_CONFLICT")
        cards = list(
            self.session.execute(
                select(MemoryCardModel).where(
                    and_(
                        MemoryCardModel.owner_id == self.user_ctx.user_id,
                        MemoryCardModel.id.in_([left_memory_id, right_memory_id]),
                        MemoryCardModel.status.in_(("active", "paused")),
                        MemoryCardModel.current_version_id.is_not(None),
                    )
                )
            ).scalars()
        )
        if len(cards) != 2:
            raise ValueError("MEMORY_NOT_FOUND")
        if left_memory_id > right_memory_id:
            left_memory_id, right_memory_id = right_memory_id, left_memory_id
        rel = MemoryRelationModel(
            id=relation_id,
            owner_id=self.user_ctx.user_id,
            from_memory_id=left_memory_id,
            to_memory_id=right_memory_id,
            relation_type="conflicts_with",
            status="unresolved",
            created_at=utc_now(),
        )
        self.session.add(rel)
        self.session.flush()
        return rel

    def list_conflicts(
        self, status: str | None = None, cursor: str | None = None
    ) -> list[MemoryRelationModel]:
        q = select(MemoryRelationModel).where(
            and_(
                MemoryRelationModel.owner_id == self.user_ctx.user_id,
                MemoryRelationModel.relation_type == "conflicts_with",
            )
        )
        if status:
            q = q.where(MemoryRelationModel.status == status)
        if cursor:
            q = q.where(MemoryRelationModel.id < cursor)
        q = q.order_by(MemoryRelationModel.created_at.desc()).limit(51)
        return list(self.session.execute(q).scalars().all())

    def get(self, relation_id: str) -> MemoryRelationModel | None:
        return self.session.execute(
            select(MemoryRelationModel).where(
                and_(
                    MemoryRelationModel.id == relation_id,
                    MemoryRelationModel.owner_id == self.user_ctx.user_id,
                    MemoryRelationModel.relation_type == "conflicts_with",
                )
            )
        ).scalar_one_or_none()

    def resolve(
        self,
        relation_id: str,
        *,
        action: str,
        resolution_memory_id: str | None = None,
    ) -> MemoryRelationModel | None:
        rel = self.get(relation_id)
        if rel is None:
            return None
        rel.status = "resolved"
        rel.resolution_action = action
        rel.resolution_memory_id = resolution_memory_id
        rel.resolved_at = utc_now()
        self.session.flush()
        return rel


# ── MemoryMergeRepository ───────────────────────────────────────────────────


class MemoryMergeRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def manual_merge(
        self,
        *,
        merged_memory_id: str,
        left_memory_id: str,
        right_memory_id: str,
        merged_card_data: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        new_version_id = new_prefixed_ulid("memver")
        scope = merged_card_data.get("scope", {})
        scope_json = json.dumps(scope, separators=(",", ":"), ensure_ascii=False)
        exc_json = json.dumps(
            merged_card_data.get("exceptions", []),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        new_card = MemoryCardModel(
            id=merged_memory_id,
            owner_id=self.user_ctx.user_id,
            status="active",
            kind=merged_card_data["kind"],
            source_type="accept",
            save_preselected=False,
            title=merged_card_data["title"],
            rule=merged_card_data["rule"],
            avoid=merged_card_data.get("avoid", ""),
            trigger_text=merged_card_data.get("trigger_text", ""),
            scope_level=scope.get("level", "global"),
            domain=scope.get("domain", "other"),
            task_type=scope.get("task_type"),
            artifact_type=scope.get("artifact_type"),
            audience=scope.get("audience"),
            project_key=scope.get("project_key"),
            scope_json=scope_json,
            exceptions_json=exc_json,
            source_trust=1.0,
            rule_confidence=1.0,
            scope_confidence=1.0,
            evidence_count=0,
            version=1,
            current_version_id=new_version_id,
            valid_from=now,
            retrieved_count=0,
            injected_count=0,
            verified_applied_count=0,
            helpful_count=0,
            harmful_count=0,
            stale_count=0,
            evidence_missing=False,
            created_at=now,
            updated_at=now,
        )
        self.session.add(new_card)
        self.session.add(
            MemoryVersionModel(
                id=new_version_id,
                owner_id=self.user_ctx.user_id,
                memory_id=merged_memory_id,
                version=1,
                title=merged_card_data["title"],
                rule=merged_card_data["rule"],
                avoid=merged_card_data.get("avoid", ""),
                trigger_text=merged_card_data.get("trigger_text", ""),
                scope_json=scope_json,
                exceptions_json=exc_json,
                created_by_action=CreatedByAction.MERGE.value,
                created_at=now,
            )
        )
        for src_id in (left_memory_id, right_memory_id):
            self.session.execute(
                update(MemoryCardModel)
                .where(
                    and_(
                        MemoryCardModel.id == src_id,
                        MemoryCardModel.owner_id == self.user_ctx.user_id,
                    )
                )
                .values(status="merged", updated_at=now)
            )
            rel_id = new_prefixed_ulid("rel")
            self.session.add(
                MemoryRelationModel(
                    id=rel_id,
                    owner_id=self.user_ctx.user_id,
                    from_memory_id=src_id,
                    to_memory_id=merged_memory_id,
                    relation_type="merged_into",
                    status="resolved",
                    resolved_at=now,
                    created_at=now,
                )
            )
        self.session.flush()
        return {
            "merged_memory_id": merged_memory_id,
            "left_status": "merged",
            "right_status": "merged",
            "new_version_id": new_version_id,
        }


# ── ImportBatchRepository ──────────────────────────────────────────────────


class ImportBatchRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def create_batch(
        self,
        *,
        batch_id: str,
        file_hash: str,
        pack_name: str | None,
        format_version: str | None,
        canonical_payload_json: str,
        preview_json: str,
        preview_token_hash: str,
        expires_at: datetime,
        legal_new_count: int = 0,
        duplicate_count: int = 0,
        conflict_count: int = 0,
        suspicious_count: int = 0,
        error_message: str | None = None,
    ) -> ImportBatchModel:
        now = utc_now()
        batch = ImportBatchModel(
            id=batch_id,
            owner_id=self.user_ctx.user_id,
            file_hash=file_hash,
            pack_name=pack_name,
            format_version=format_version,
            status="quarantined",
            canonical_payload_json=canonical_payload_json,
            preview_json=preview_json,
            preview_token_hash=preview_token_hash,
            expires_at=expires_at,
            inserted_count=legal_new_count,
            skipped_count=duplicate_count + conflict_count + suspicious_count,
            warning_count=conflict_count + suspicious_count,
            error_message=error_message,
            created_at=now,
            updated_at=now,
        )
        self.session.add(batch)
        self.session.flush()
        return batch

    def get_batch(self, batch_id: str) -> ImportBatchModel | None:
        return self.session.execute(
            select(ImportBatchModel).where(
                and_(
                    ImportBatchModel.id == batch_id,
                    ImportBatchModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()

    def commit(
        self, batch_id: str, inserted_count: int, skipped_count: int
    ) -> ImportBatchModel | None:
        batch = self.get_batch(batch_id)
        if batch is None:
            return None
        batch.status = "committed"
        batch.committed_at = utc_now()
        batch.inserted_count = inserted_count
        batch.skipped_count = skipped_count
        batch.canonical_payload_json = None
        batch.preview_json = None
        batch.preview_token_hash = None
        batch.updated_at = batch.committed_at
        self.session.flush()
        return batch

    def cancel(self, batch_id: str) -> ImportBatchModel | None:
        batch = self.get_batch(batch_id)
        if batch is None:
            return None
        batch.status = "cancelled"
        batch.canonical_payload_json = None
        batch.preview_json = None
        batch.preview_token_hash = None
        batch.updated_at = utc_now()
        self.session.flush()
        return batch


# ── PackRepository ──────────────────────────────────────────────────────────


class PackRepository:
    MAX_PACK_SIZE = 1_048_576
    MAX_CARDS = 200
    MAX_DEPTH = 12
    MAX_STRING = 10_000

    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def export_memories(
        self,
        *,
        pack_id: str,
        name: str,
        description: str,
        memory_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if memory_ids:
            cards = list(
                self.session.execute(
                    select(MemoryCardModel).where(
                        and_(
                            MemoryCardModel.owner_id == self.user_ctx.user_id,
                            MemoryCardModel.id.in_(memory_ids),
                            MemoryCardModel.status.notin_(("candidate", "rejected", "deleted")),
                            MemoryCardModel.current_version_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(cards) != len(set(memory_ids)):
                raise ValueError("memory selection is missing or cross-owner")
        else:
            cards = list(
                self.session.execute(
                    select(MemoryCardModel).where(
                        and_(
                            MemoryCardModel.owner_id == self.user_ctx.user_id,
                            MemoryCardModel.status.in_(("active", "paused")),
                            MemoryCardModel.current_version_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
        cards.sort(key=lambda card: card.id)
        local_to_external = {card.id: f"card_{index:03d}" for index, card in enumerate(cards, 1)}
        export_cards: list[dict[str, Any]] = []
        for card in cards:
            if card.current_version_id is None:
                continue
            ver = self.session.execute(
                select(MemoryVersionModel).where(
                    and_(
                        MemoryVersionModel.id == card.current_version_id,
                        MemoryVersionModel.owner_id == self.user_ctx.user_id,
                    )
                )
            ).scalar_one_or_none()
            if ver is None:
                continue
            scope_dict: dict[str, Any] = json.loads(card.scope_json)
            export_cards.append(
                {
                    "external_id": local_to_external[card.id],
                    "schema_version": "1.0",
                    "kind": card.kind,
                    "title": card.title,
                    "rule": card.rule,
                    "avoid": card.avoid or "",
                    "trigger_text": card.trigger_text or "",
                    "scope": scope_dict,
                    "exceptions": json.loads(card.exceptions_json),
                    "claimed_origin": {
                        "source_type": card.source_type,
                        "trust_level": (
                            "imported_unverified"
                            if card.source_type == "import"
                            else "user_confirmed"
                        ),
                        "created_at": self._rfc3339(card.created_at),
                        "source_task_exported": False,
                        "source_version": card.version or 1,
                    },
                    "version": card.version,
                    "updated_at": self._rfc3339(card.updated_at),
                }
            )
        exported_ids = set(local_to_external)
        relations: list[dict[str, Any]] = []
        if len(exported_ids) > 1:
            for rel in (
                self.session.execute(
                    select(MemoryRelationModel).where(
                        and_(
                            MemoryRelationModel.owner_id == self.user_ctx.user_id,
                            MemoryRelationModel.from_memory_id.in_(exported_ids),
                            MemoryRelationModel.to_memory_id.in_(exported_ids),
                        )
                    )
                )
                .scalars()
                .all()
            ):
                relations.append(
                    {
                        "from_external_id": local_to_external[rel.from_memory_id],
                        "to_external_id": local_to_external[rel.to_memory_id],
                        "relation_type": rel.relation_type,
                    }
                )
        pack: dict[str, Any] = {
            "schema_ref": "memtrace-memory-pack@1.0.0",
            "format": "memtrace-memory-pack",
            "format_version": "1.0.0",
            "pack_id": pack_id,
            "name": name,
            "description": description,
            "created_at": self._rfc3339(utc_now()),
            "producer": {"name": "MemTrace", "version": "0.1.0"},
            "source": {"kind": "user_export", "trust": "self_asserted"},
            "privacy": {"contains_raw_evidence": False, "anonymized": True},
            "cards": export_cards,
            "relations": relations,
        }
        canonical_bytes = _rfc8785_canonical_bytes(pack)
        pack["integrity"] = {
            "algorithm": "sha256",
            "canonical_payload_sha256": _sha256_hex(canonical_bytes),
        }
        return pack

    @staticmethod
    def _rfc3339(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def canonical_bytes(pack: dict[str, Any]) -> bytes:
        return _rfc8785_canonical_bytes(pack)

    def existing_cards_for_preview(self) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(MemoryCardModel).where(
                and_(
                    MemoryCardModel.owner_id == self.user_ctx.user_id,
                    MemoryCardModel.status != "deleted",
                    MemoryCardModel.current_version_id.is_not(None),
                )
            )
        ).scalars()
        return [
            {
                "kind": card.kind,
                "title": card.title,
                "rule": card.rule,
                "avoid": card.avoid or "",
                "trigger_text": card.trigger_text or "",
                "scope": json.loads(card.scope_json),
                "exceptions": json.loads(card.exceptions_json),
            }
            for card in rows
        ]

    @staticmethod
    def encode_preview_token(
        secret: str,
        owner_id: str,
        batch_id: str,
        file_hash: str,
        exp_ts: int,
    ) -> str:
        payload = f"{owner_id}|{batch_id}|{file_hash}|{exp_ts}".encode()
        mac = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")

    @staticmethod
    def verify_preview_token(
        secret: str,
        token: str,
        owner_id: str,
        batch_id: str,
        file_hash: str,
        exp_ts: int,
    ) -> bool:
        if len(token) != 43:
            return False
        expected = PackRepository.encode_preview_token(
            secret, owner_id, batch_id, file_hash, exp_ts
        )
        return secrets.compare_digest(token, expected)
