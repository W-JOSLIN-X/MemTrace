"""SQLAlchemy declarative base and G1/G2 SQLite schema models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    feedback_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("feedback_events.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disposition: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
            "stage IN ('queued', 'diffing', 'classifying_durability', 'extracting', "
            "'validating', 'admitting', 'done', 'failed')",
            name="chk_job_stage",
        ),
        CheckConstraint(
            "disposition IS NULL OR disposition IN "
            "('candidate_created', 'episode_only', 'reinforce_usage_only', "
            "'no_memory', 'failed')",
            name="chk_job_disposition",
        ),
    )

    feedback: Mapped[FeedbackEventModel] = relationship(
        "FeedbackEventModel", back_populates="memory_job"
    )
    cards: Mapped[list[MemoryCardModel]] = relationship("MemoryCardModel", back_populates="job")
    evidence_rows: Mapped[list[MemoryEvidenceModel]] = relationship(
        "MemoryEvidenceModel", back_populates="job"
    )


# ======================================================================================
# Day 3 G2 memory admission tables. All queries filter by owner_id; ID columns use
# String(64) to hold "prefix + 26-char ULID" comfortably.
# ======================================================================================


class MemoryCardModel(Base):
    __tablename__ = "memory_cards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    memory_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("memory_jobs.id", ondelete="SET NULL"), nullable=True
    )
    # No FK by design: cards <-> versions are mutually referential and SQLite
    # cannot ADD CONSTRAINT after creation. The resolve transaction updates the
    # pair atomically.
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    save_preselected: Mapped[bool] = mapped_column(nullable=False, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    avoid: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trigger_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scope_level: Mapped[str] = mapped_column(String(32), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audience: Mapped[str | None] = mapped_column(String(32), nullable=True)
    project_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scope_json: Mapped[str] = mapped_column(Text, nullable=False)
    exceptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_trust: Mapped[float] = mapped_column(Float, nullable=False)
    rule_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    scope_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # G3 retrieval counters
    retrieved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified_applied_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    helpful_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    harmful_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'active', 'rejected', 'conflicted', 'paused', "
            "'superseded', 'merged', 'archived', 'deleted')",
            name="chk_memory_card_status",
        ),
        CheckConstraint(
            "kind IN ('preference', 'constraint', 'procedure', 'experience', "
            "'environment', 'learning_checkpoint')",
            name="chk_memory_card_kind",
        ),
        CheckConstraint(
            "source_type IN ('explicit_feedback', 'explicit_correction', 'edit_diff', "
            "'accept', 'reject', 'rating', 'outcome', 'import')",
            name="chk_memory_card_source_type",
        ),
        CheckConstraint(
            "rejection_reason IS NULL OR rejection_reason IN ('user_rejected', 'episode_only')",
            name="chk_memory_card_rejection_reason",
        ),
        CheckConstraint(
            "scope_level IN ('session', 'task_family', 'project', 'global')",
            name="chk_memory_card_scope_level",
        ),
        CheckConstraint(
            "domain IN ('programming_learning', 'software_development', "
            "'general_text', 'other', 'any')",
            name="chk_memory_card_domain",
        ),
        CheckConstraint(
            "task_type IS NULL OR task_type IN ('debugging_guidance', 'code_review', "
            "'code_explanation', 'code_generation', 'environment_configuration', "
            "'general_question', 'other')",
            name="chk_memory_card_task_type",
        ),
        CheckConstraint(
            "artifact_type IS NULL OR artifact_type IN ('source_code', "
            "'configuration', 'text', 'none', 'other')",
            name="chk_memory_card_artifact_type",
        ),
        CheckConstraint(
            "audience IS NULL OR audience IN ('beginner', 'intermediate', 'advanced', 'unknown')",
            name="chk_memory_card_audience",
        ),
        CheckConstraint(
            "status != 'candidate' OR (version = 0 AND current_version_id IS NULL "
            "AND rule_confidence IS NULL AND scope_confidence IS NULL)",
            name="chk_memory_card_candidate_invariants",
        ),
        CheckConstraint(
            "status != 'active' OR (version >= 1 AND current_version_id IS NOT NULL "
            "AND rule_confidence IS NOT NULL AND scope_confidence IS NOT NULL)",
            name="chk_memory_card_active_invariants",
        ),
        CheckConstraint("source_trust >= 0 AND source_trust <= 1", name="chk_memory_card_trust"),
        Index("ix_memory_cards_owner_status", "owner_id", "status"),
        Index(
            "ix_memory_cards_owner_status_scope",
            "owner_id",
            "status",
            "domain",
            "task_type",
            "project_key",
        ),
        Index("ix_memory_cards_job", "memory_job_id"),
        Index("ix_memory_cards_current_version", "current_version_id"),
    )

    job: Mapped[MemoryJobModel | None] = relationship("MemoryJobModel", back_populates="cards")
    versions: Mapped[list[MemoryVersionModel]] = relationship(
        "MemoryVersionModel", back_populates="memory"
    )
    evidence_links: Mapped[list[MemoryEvidenceLinkModel]] = relationship(
        "MemoryEvidenceLinkModel", back_populates="memory"
    )


class MemoryVersionModel(Base):
    __tablename__ = "memory_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    avoid: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trigger_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scope_json: Mapped[str] = mapped_column(Text, nullable=False)
    exceptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_by_action: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("version >= 1", name="chk_memory_version_number"),
        CheckConstraint(
            "created_by_action IN ('accept', 'edit_accept')",
            name="chk_memory_version_created_by",
        ),
        UniqueConstraint("memory_id", "version", name="uq_memory_version_number"),
        Index("ix_memory_versions_memory", "memory_id"),
        Index("ix_memory_versions_owner", "owner_id"),
    )

    memory: Mapped[MemoryCardModel] = relationship("MemoryCardModel", back_populates="versions")


class MemoryEvidenceModel(Base):
    __tablename__ = "memory_evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    feedback_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("feedback_events.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    memory_job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_jobs.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_field: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    diff_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_edit_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    episode_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('explicit_feedback', 'explicit_correction', 'edit_diff', "
            "'accept', 'reject', 'rating', 'outcome', 'import')",
            name="chk_memory_evidence_source_type",
        ),
        CheckConstraint(
            "source_field IN ('explicit_text', 'edited_output', 'rating', 'accepted')",
            name="chk_memory_evidence_source_field",
        ),
        CheckConstraint(
            "normalized_edit_cost IS NULL OR "
            "(normalized_edit_cost >= 0 AND normalized_edit_cost <= 1)",
            name="chk_memory_evidence_edit_cost",
        ),
        CheckConstraint(
            "disposition IS NULL OR disposition IN "
            "('candidate_created', 'episode_only', 'reinforce_usage_only', "
            "'no_memory', 'failed')",
            name="chk_memory_evidence_disposition",
        ),
        Index("ix_memory_evidence_owner", "owner_id"),
        Index("ix_memory_evidence_job", "memory_job_id"),
        Index("ix_memory_evidence_feedback", "feedback_id"),
    )

    job: Mapped[MemoryJobModel] = relationship("MemoryJobModel", back_populates="evidence_rows")
    links: Mapped[list[MemoryEvidenceLinkModel]] = relationship(
        "MemoryEvidenceLinkModel", back_populates="evidence"
    )


class MemoryEvidenceLinkModel(Base):
    __tablename__ = "memory_evidence_links"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_evidence.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("ordinal >= 0 AND ordinal <= 2", name="chk_evidence_link_ordinal"),
        UniqueConstraint("memory_id", "evidence_id", name="uq_evidence_link_pair"),
        Index("ix_memory_evidence_links_memory", "memory_id"),
    )

    memory: Mapped[MemoryCardModel] = relationship(
        "MemoryCardModel", back_populates="evidence_links"
    )
    evidence: Mapped[MemoryEvidenceModel] = relationship(
        "MemoryEvidenceModel", back_populates="links"
    )


class MemoryRelationModel(Base):
    __tablename__ = "memory_relations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    from_memory_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False
    )
    to_memory_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "relation_type IN ('duplicate_of', 'conflicts_with', 'supersedes', 'related_to')",
            name="chk_memory_relation_type",
        ),
        CheckConstraint("from_memory_id != to_memory_id", name="chk_memory_relation_self"),
        UniqueConstraint(
            "from_memory_id", "to_memory_id", "relation_type", name="uq_memory_relation_triple"
        ),
        Index("ix_memory_relations_from", "from_memory_id"),
        Index("ix_memory_relations_to", "to_memory_id"),
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


# ===========================================================================
# Day 4 G3 retrieval, usage, and verification models
# ===========================================================================


class RetrievalTraceModel(Base):
    __tablename__ = "retrieval_traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    retrieval_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retrieved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decisions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    retrieval_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memory_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memory_tokens_estimated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_prompt_tokens_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_section_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_id", "run_id", name="uq_retrieval_trace_owner_run"),
        Index("ix_retrieval_traces_task", "task_id"),
    )


class RetrievalDecisionModel(Base):
    __tablename__ = "retrieval_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    retrieval_trace_id: Mapped[str] = mapped_column(String(64), ForeignKey("retrieval_traces.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_id: Mapped[str] = mapped_column(String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_version_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("memory_versions.id", ondelete="SET NULL"), nullable=True)
    memory_status: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    injected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    semantic_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    provenance_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    recency: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("retrieval_trace_id", "memory_id", name="uq_retrieval_decision_trace_memory"),
        Index("ix_retrieval_decisions_trace", "retrieval_trace_id"),
    )


class MemoryUsageModel(Base):
    __tablename__ = "memory_usages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    retrieval_trace_id: Mapped[str] = mapped_column(String(64), ForeignKey("retrieval_traces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_id: Mapped[str] = mapped_column(String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_version_id: Mapped[str] = mapped_column(String(64), ForeignKey("memory_versions.id", ondelete="CASCADE"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    injected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    verification_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_effect: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_id", "run_id", "memory_id", "memory_version_id", name="uq_memory_usage_owner_run_memory_version"),
        Index("ix_memory_usages_trace", "retrieval_trace_id"),
        Index("ix_memory_usages_memory", "memory_id"),
    )


class MemoryVerificationJobModel(Base):
    __tablename__ = "memory_verification_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_usage_id: Mapped[str] = mapped_column(String(64), ForeignKey("memory_usages.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
