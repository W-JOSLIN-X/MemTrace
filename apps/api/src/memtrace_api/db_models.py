"""SQLAlchemy declarative base and G1 SQLite schema models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from memtrace_api.schemas import utc_now


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    demo_alias: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    sessions: Mapped[list[DemoSessionModel]] = relationship(
        "DemoSessionModel", back_populates="owner", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[TaskModel]] = relationship(
        "TaskModel", back_populates="owner", cascade="all, delete-orphan"
    )


class DemoSessionModel(Base):
    __tablename__ = "demo_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    owner: Mapped[UserModel] = relationship("UserModel", back_populates="sessions")


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scenario: Mapped[str] = mapped_column(String(64), nullable=False)
    task_text: Mapped[str] = mapped_column(Text, nullable=False)
    effective_memory_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    next_event_seq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "scenario IN ('programming_learning', 'software_development', 'general_text', 'other')",
            name="chk_task_scenario",
        ),
        CheckConstraint("effective_memory_mode IN ('on', 'off')", name="chk_task_memory_mode"),
        CheckConstraint("status IN ('active', 'archived')", name="chk_task_status"),
    )

    owner: Mapped[UserModel] = relationship("UserModel", back_populates="tasks")
    fingerprint: Mapped[TaskFingerprintModel | None] = relationship(
        "TaskFingerprintModel", back_populates="task", uselist=False, cascade="all, delete-orphan"
    )
    runs: Mapped[list[AgentRunModel]] = relationship(
        "AgentRunModel", back_populates="task", cascade="all, delete-orphan"
    )
    messages: Mapped[list[MessageModel]] = relationship(
        "MessageModel", back_populates="task", cascade="all, delete-orphan"
    )
    tool_calls: Mapped[list[ToolCallModel]] = relationship(
        "ToolCallModel", back_populates="task", cascade="all, delete-orphan"
    )
    feedback_events: Mapped[list[FeedbackEventModel]] = relationship(
        "FeedbackEventModel", back_populates="task", cascade="all, delete-orphan"
    )


class TaskFingerprintModel(Base):
    __tablename__ = "task_fingerprints"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fingerprint_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    task: Mapped[TaskModel] = relationship("TaskModel", back_populates="fingerprint")


class AgentRunModel(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_source: Mapped[str] = mapped_column(String(32), nullable=False)
    first_token_ms: Mapped[float | None] = mapped_column(nullable=True)
    total_ms: Mapped[float | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("provider_mode IN ('mock', 'real')", name="chk_run_provider_mode"),
        CheckConstraint(
            "token_source IN ('actual', 'unavailable', 'mock')", name="chk_run_token_source"
        ),
        CheckConstraint(
            "status IN ('queued', 'fingerprinting', 'retrieving', 'planning', "
            "'tool_running', 'generating', 'succeeded', 'failed')",
            name="chk_run_status",
        ),
    )

    task: Mapped[TaskModel] = relationship("TaskModel", back_populates="runs")
    messages: Mapped[list[MessageModel]] = relationship(
        "MessageModel", back_populates="run", cascade="all, delete-orphan"
    )
    tool_calls: Mapped[list[ToolCallModel]] = relationship(
        "ToolCallModel", back_populates="run", cascade="all, delete-orphan"
    )
    feedback_events: Mapped[list[FeedbackEventModel]] = relationship(
        "FeedbackEventModel", back_populates="run", cascade="all, delete-orphan"
    )


class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')", name="chk_message_role"),)

    task: Mapped[TaskModel] = relationship("TaskModel", back_populates="messages")
    run: Mapped[AgentRunModel | None] = relationship("AgentRunModel", back_populates="messages")


class ToolCallModel(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    args_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    result_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="chk_tool_status"),
    )

    task: Mapped[TaskModel] = relationship("TaskModel", back_populates="tool_calls")
    run: Mapped[AgentRunModel] = relationship("AgentRunModel", back_populates="tool_calls")


class FeedbackEventModel(Base):
    __tablename__ = "feedback_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)
    explicit_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accepted: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "feedback_type IN ('explicit_text', 'edited_output', 'rating', "
            "'accepted', 'rejected', 'composite')",
            name="chk_feedback_type",
        ),
        CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)", name="chk_feedback_rating"
        ),
    )

    task: Mapped[TaskModel] = relationship("TaskModel", back_populates="feedback_events")
    run: Mapped[AgentRunModel] = relationship("AgentRunModel", back_populates="feedback_events")
    memory_job: Mapped[MemoryJobModel | None] = relationship(
        "MemoryJobModel", back_populates="feedback", uselist=False, cascade="all, delete-orphan"
    )


class MemoryJobModel(Base):
    __tablename__ = "memory_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    feedback_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("feedback_events.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("job_type IN ('extract_feedback')", name="chk_job_type"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')", name="chk_job_status"
        ),
        CheckConstraint(
            "stage IN ('queued', 'extracting', 'done', 'failed')", name="chk_job_stage"
        ),
    )

    feedback: Mapped[FeedbackEventModel] = relationship(
        "FeedbackEventModel", back_populates="memory_job"
    )


class EventLogModel(Base):
    __tablename__ = "event_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stream_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stream_id: Mapped[str] = mapped_column(String(32), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "owner_id", "stream_type", "stream_id", "seq", name="uq_event_log_stream_seq"
        ),
        Index("ix_event_log_stream", "stream_type", "stream_id", "seq"),
    )


class IdempotencyKeyModel(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    route: Mapped[str] = mapped_column(String(256), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "route", "key", name="uq_idempotency_owner_route_key"),
        Index("ix_idempotency_lookup", "owner_id", "route", "key"),
    )
