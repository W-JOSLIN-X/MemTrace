"""Data repositories with UserContext owner isolation for G1 persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from memtrace_api.db_models import (
    AgentRunModel,
    DemoSessionModel,
    EventLogModel,
    FeedbackEventModel,
    IdempotencyKeyModel,
    MemoryJobModel,
    MessageModel,
    TaskFingerprintModel,
    TaskModel,
    ToolCallModel,
    UserModel,
)
from memtrace_api.events import EventType
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.schemas import (
    AsyncErrorCode,
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
        # Revoke existing active sessions for this user to prevent dangling sessions
        now = utc_now()
        self.session.execute(
            update(DemoSessionModel)
            .where(
                and_(
                    DemoSessionModel.owner_id == owner_id,
                    DemoSessionModel.revoked_at.is_(None),
                )
            )
            .values(revoked_at=now)
        )
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
                )
            )
        ).scalar_one_or_none()

    def allocate_next_event_seq(self, task_id: str) -> int:
        """Atomically increment and return the next event seq for this owner's task."""
        row = self.session.execute(
            select(TaskModel.next_event_seq)
            .where(
                and_(
                    TaskModel.id == task_id,
                    TaskModel.owner_id == self.user_ctx.user_id,
                )
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise ValueError(f"task not found for event seq allocation: {task_id}")
        seq = row
        self.session.execute(
            update(TaskModel)
            .where(
                and_(
                    TaskModel.id == task_id,
                    TaskModel.owner_id == self.user_ctx.user_id,
                )
            )
            .values(next_event_seq=seq + 1, updated_at=utc_now())
        )
        return seq

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

    def get_memory_job(self, job_id: str) -> MemoryJobModel | None:
        return self.session.execute(
            select(MemoryJobModel).where(
                and_(
                    MemoryJobModel.id == job_id,
                    MemoryJobModel.owner_id == self.user_ctx.user_id,
                )
            )
        ).scalar_one_or_none()


class IdempotencyRepository:
    def __init__(self, user_ctx: UserContext, session: Session) -> None:
        self.user_ctx = user_ctx
        self.session = session

    def get_record(self, route: str, key: str) -> IdempotencyKeyModel | None:
        now = utc_now()
        # Delete if expired
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
