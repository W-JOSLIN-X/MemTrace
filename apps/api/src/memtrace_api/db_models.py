"""SQLAlchemy declarative base and G1/G2 SQLite schema models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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
    conversation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_through_turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_turn_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # G4 task tombstone fields
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
        CheckConstraint(
            "status IN ('active', 'archived', 'deleted')",
            name="chk_task_status",
        ),
        CheckConstraint(
            "(status = 'deleted' AND deleted_at IS NOT NULL AND task_text = '') OR "
            "(status != 'deleted' AND deleted_at IS NULL AND deleted_by IS NULL "
            "AND deletion_reason IS NULL)",
            name="chk_task_deleted_tombstone",
        ),
        CheckConstraint(
            "summary_through_turn >= 0 AND next_turn_index >= 1",
            name="chk_task_conversation_cursors",
        ),
        UniqueConstraint("owner_id", "id", name="uq_tasks_owner_id"),
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
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_source: Mapped[str] = mapped_column(String(32), nullable=False)
    first_token_ms: Mapped[float | None] = mapped_column(nullable=True)
    total_ms: Mapped[float | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_response_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
        CheckConstraint(
            "(total_tokens IS NULL OR total_tokens >= 0) AND "
            "(reasoning_tokens IS NULL OR reasoning_tokens >= 0)",
            name="chk_run_extended_usage",
        ),
        UniqueConstraint("owner_id", "task_id", "id", name="uq_agent_runs_owner_task_id"),
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
    turn_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="chk_message_role"),
        CheckConstraint("turn_index IS NULL OR turn_index >= 1", name="chk_message_turn_index"),
        UniqueConstraint("owner_id", "id", name="uq_messages_owner_id"),
        Index("ix_messages_owner_task_turn", "owner_id", "task_id", "turn_index", "role"),
    )

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
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    save_preselected: Mapped[bool] = mapped_column(nullable=False, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # v2 fields (added by 006 migration)
    memory_kind_v2: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    applies_when: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rule_subtype: Mapped[str | None] = mapped_column(String(32), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # v1 fields (legacy, kept for compatibility)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    avoid: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    trigger_text: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    scope_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audience: Mapped[str | None] = mapped_column(String(32), nullable=True)
    project_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scope_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    exceptions_json: Mapped[str | None] = mapped_column(Text, nullable=True, default="[]")
    source_trust: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    # G4 memory center / pack fields
    evidence_missing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    import_source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'pending', 'active', 'rejected', 'conflicted', 'paused', "
            "'superseded', 'merged', 'archived', 'deleted')",
            name="chk_memory_card_status",
        ),
        CheckConstraint(
            "kind IN ('preference', 'constraint', 'procedure', 'experience', "
            "'environment', 'learning_checkpoint')",
            name="chk_memory_card_kind",
        ),
        CheckConstraint(
            "source_type IS NULL OR source_type IN ('explicit_feedback', "
            "'explicit_correction', 'edit_diff', 'accept', 'reject', 'rating', "
            "'outcome', 'import', 'conversation_turn', 'user_edit')",
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
            "'general_question', 'other', 'any')",
            name="chk_memory_card_task_type",
        ),
        CheckConstraint(
            "artifact_type IS NULL OR artifact_type IN ('source_code', "
            "'configuration', 'text', 'none', 'other', 'any')",
            name="chk_memory_card_artifact_type",
        ),
        CheckConstraint(
            "audience IS NULL OR audience IN "
            "('beginner', 'intermediate', 'advanced', 'unknown', 'any')",
            name="chk_memory_card_audience",
        ),
        CheckConstraint(
            "status != 'candidate' OR (version = 0 AND current_version_id IS NULL "
            "AND rule_confidence IS NULL AND scope_confidence IS NULL)",
            name="chk_memory_card_candidate_invariants",
        ),
        CheckConstraint(
            "status NOT IN ('active', 'paused') OR "
            "(version >= 1 AND current_version_id IS NOT NULL "
            "AND rule_confidence IS NOT NULL AND scope_confidence IS NOT NULL)",
            name="chk_memory_card_active_invariants",
        ),
        CheckConstraint("source_trust >= 0 AND source_trust <= 1", name="chk_memory_card_trust"),
        CheckConstraint(
            "retrieved_count >= 0 AND injected_count >= 0 "
            "AND verified_applied_count >= 0 AND helpful_count >= 0 "
            "AND harmful_count >= 0 AND stale_count >= 0",
            name="chk_memory_card_g3_counters",
        ),
        CheckConstraint(
            "(status = 'deleted' AND deleted_at IS NOT NULL) OR "
            "(status != 'deleted' AND deleted_at IS NULL)",
            name="chk_memory_card_g4_deleted_tombstone",
        ),
        CheckConstraint(
            "(status = 'deleted' AND kind IS NULL AND source_type IS NULL "
            "AND title IS NULL AND rule IS NULL AND avoid IS NULL "
            "AND trigger_text IS NULL AND scope_level IS NULL AND domain IS NULL "
            "AND scope_json IS NULL AND exceptions_json IS NULL "
            "AND source_trust IS NULL AND current_version_id IS NULL "
            "AND version = 0 AND evidence_count = 0 AND retrieved_count = 0 "
            "AND injected_count = 0 AND verified_applied_count = 0 "
            "AND helpful_count = 0 AND harmful_count = 0 AND stale_count = 0) OR "
            "(status != 'deleted' AND kind IS NOT NULL AND source_type IS NOT NULL "
            "AND title IS NOT NULL AND rule IS NOT NULL AND avoid IS NOT NULL "
            "AND trigger_text IS NOT NULL AND scope_level IS NOT NULL "
            "AND domain IS NOT NULL AND scope_json IS NOT NULL "
            "AND exceptions_json IS NOT NULL AND source_trust IS NOT NULL)",
            name="chk_memory_card_g4_content_state",
        ),
        CheckConstraint(
            "import_source_version IS NULL OR import_source_version >= 1",
            name="chk_memory_card_import_source_version",
        ),
        CheckConstraint(
            "memory_kind_v2 IS NULL OR memory_kind_v2 IN ('preference', 'rule', 'experience')",
            name="chk_memory_card_v2_kind",
        ),
        CheckConstraint(
            "review_status IS NULL OR review_status IN "
            "('active', 'pending', 'paused', 'archived', 'superseded', "
            "'legacy_unverified')",
            name="chk_memory_card_review_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_memory_card_v2_confidence",
        ),
        CheckConstraint(
            "rule_subtype IS NULL OR rule_subtype IN ('constraint', 'procedure')",
            name="chk_memory_card_rule_subtype",
        ),
        CheckConstraint(
            "schema_version IS NULL OR schema_version != '2.0' OR status = 'deleted' OR "
            "(memory_kind_v2 IS NOT NULL AND content IS NOT NULL AND content != '' "
            "AND applies_when IS NOT NULL AND applies_when != '' "
            "AND review_status IS NOT NULL AND confidence IS NOT NULL)",
            name="chk_memory_card_v2_required",
        ),
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
        Index("ix_memory_cards_deleted_at", "deleted_at"),
        Index("ix_memory_cards_import_batch", "import_batch_id"),
        Index("ix_memory_cards_owner_review_updated", "owner_id", "review_status", "updated_at"),
        Index("ix_memory_cards_owner_v2_kind", "owner_id", "memory_kind_v2"),
        UniqueConstraint("owner_id", "id", name="uq_memory_cards_owner_id"),
    )

    job: Mapped[MemoryJobModel | None] = relationship("MemoryJobModel", back_populates="cards")
    versions: Mapped[list[MemoryVersionModel]] = relationship(
        "MemoryVersionModel", back_populates="memory"
    )
    evidence_links: Mapped[list[MemoryEvidenceLinkModel]] = relationship(
        "MemoryEvidenceLinkModel", back_populates="memory"
    )
    import_batch: Mapped[ImportBatchModel | None] = relationship(
        "ImportBatchModel", back_populates="cards"
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
    # v2 fields (added by 006 migration)
    memory_kind_v2: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    applies_when: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rule_subtype: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        CheckConstraint("version >= 1", name="chk_memory_version_number"),
        CheckConstraint(
            "created_by_action IN ('accept', 'edit_accept', 'edit', "
            "'import', 'merge', 'scope_resolution', 'llm_extract', 'llm_update', "
            "'llm_supersede', 'llm_coexist', 'user_edit')",
            name="chk_memory_version_created_by",
        ),
        CheckConstraint(
            "memory_kind_v2 IS NULL OR memory_kind_v2 IN ('preference', 'rule', 'experience')",
            name="chk_memory_version_v2_kind",
        ),
        UniqueConstraint("memory_id", "version", name="uq_memory_version_number"),
        UniqueConstraint("owner_id", "id", name="uq_memory_versions_owner_id"),
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
    feedback_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("feedback_events.id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    memory_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("memory_jobs.id", ondelete="CASCADE"), nullable=True
    )
    reflection_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # v2: message_id links evidence directly to the user message that triggered it
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    turn_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    consolidation_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consolidation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
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
            "'accept', 'reject', 'rating', 'outcome', 'import', 'conversation_turn', "
            "'user_edit')",
            name="chk_memory_evidence_source_type",
        ),
        CheckConstraint(
            "source_field IN ('explicit_text', 'edited_output', 'rating', 'accepted', "
            "'user_message')",
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
        CheckConstraint(
            "feedback_id IS NOT NULL OR message_id IS NOT NULL",
            name="chk_memory_evidence_reference",
        ),
        CheckConstraint(
            "turn_index IS NULL OR turn_index >= 1",
            name="chk_memory_evidence_turn_index",
        ),
        CheckConstraint(
            "consolidation_confidence IS NULL OR "
            "(consolidation_confidence >= 0 AND consolidation_confidence <= 1)",
            name="chk_memory_evidence_consolidation_confidence",
        ),
        ForeignKeyConstraint(
            ["owner_id", "reflection_job_id"],
            ["memory_reflection_jobs.owner_id", "memory_reflection_jobs.id"],
            name="fk_memory_evidence_reflection_job",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "message_id"],
            ["messages.owner_id", "messages.id"],
            name="fk_memory_evidence_message_owner",
            ondelete="CASCADE",
        ),
        Index("ix_memory_evidence_owner", "owner_id"),
        Index("ix_memory_evidence_job", "memory_job_id"),
        Index("ix_memory_evidence_feedback", "feedback_id"),
        Index("ix_memory_evidence_reflection_job", "owner_id", "reflection_job_id"),
        Index("ix_memory_evidence_message", "owner_id", "message_id"),
    )

    job: Mapped[MemoryJobModel | None] = relationship(
        "MemoryJobModel", back_populates="evidence_rows"
    )
    reflection_job: Mapped[MemoryReflectionJobModel | None] = relationship(
        "MemoryReflectionJobModel", foreign_keys=[reflection_job_id]
    )
    message: Mapped[MessageModel | None] = relationship("MessageModel", foreign_keys=[message_id])
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
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_memory_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False
    )
    to_memory_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="resolved")
    resolution_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_memory_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    llm_consolidation_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consolidation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    consolidation_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "relation_type IN ('duplicate_of', 'conflicts_with', 'supersedes', "
            "'reinforces', 'merged_into', 'related_to')",
            name="chk_memory_relation_type",
        ),
        CheckConstraint(
            "status IN ('unresolved', 'resolved')",
            name="chk_memory_relation_status",
        ),
        CheckConstraint(
            "resolution_action IS NULL OR resolution_action IN "
            "('prefer', 'separate_scopes', 'merge', 'pause_both')",
            name="chk_memory_relation_resolution_action",
        ),
        CheckConstraint("from_memory_id != to_memory_id", name="chk_memory_relation_self"),
        UniqueConstraint(
            "from_memory_id", "to_memory_id", "relation_type", name="uq_memory_relation_triple"
        ),
        CheckConstraint(
            "(status = 'unresolved' AND relation_type = 'conflicts_with' "
            "AND resolution_action IS NULL AND resolution_memory_id IS NULL "
            "AND resolved_at IS NULL) OR "
            "(status = 'resolved' AND (relation_type != 'conflicts_with' OR "
            "(resolution_action IS NOT NULL AND resolved_at IS NOT NULL)))",
            name="chk_memory_relation_resolution_state",
        ),
        CheckConstraint(
            "llm_consolidation_decision IS NULL OR llm_consolidation_decision IN "
            "('add', 'update', 'supersede', 'coexist', 'noop')",
            name="chk_memory_relation_llm_decision",
        ),
        CheckConstraint(
            "consolidation_confidence IS NULL OR "
            "(consolidation_confidence >= 0 AND consolidation_confidence <= 1)",
            name="chk_memory_relation_llm_confidence",
        ),
        ForeignKeyConstraint(
            ["owner_id", "from_memory_id"],
            ["memory_cards.owner_id", "memory_cards.id"],
            name="fk_memory_relations_from_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "to_memory_id"],
            ["memory_cards.owner_id", "memory_cards.id"],
            name="fk_memory_relations_to_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "resolution_memory_id"],
            ["memory_cards.owner_id", "memory_cards.id"],
            name="fk_memory_relations_resolution_owner",
            ondelete="SET NULL",
        ),
        Index("ix_memory_relations_from", "from_memory_id"),
        Index("ix_memory_relations_to", "to_memory_id"),
        Index("ix_memory_relations_owner_status", "owner_id", "status"),
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
        Index("ix_idempotency_lookup", "owner_id", "route", "key", "expires_at"),
    )


# ===========================================================================
# Day 4 G3 retrieval, usage, and verification models
# ===========================================================================


class RetrievalTraceModel(Base):
    __tablename__ = "retrieval_traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "run_id", name="uq_retrieval_trace_owner_run"),
        CheckConstraint(
            "retrieval_mode IN ('tfidf', 'tfidf_degraded', 'llm_judge')",
            name="chk_retrieval_trace_mode",
        ),
        CheckConstraint("retrieval_ms >= 0", name="chk_retrieval_trace_ms"),
        CheckConstraint("threshold >= 0 AND threshold <= 1", name="chk_retrieval_trace_threshold"),
        CheckConstraint("top_k > 0", name="chk_retrieval_trace_top_k"),
        CheckConstraint(
            "candidate_count >= 0 AND retrieved_count >= 0 AND selected_count >= 0 "
            "AND injected_count >= 0",
            name="chk_retrieval_trace_counts",
        ),
        Index("ix_retrieval_traces_owner_task", "owner_id", "task_id"),
    )


class RetrievalDecisionModel(Base):
    __tablename__ = "retrieval_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    retrieval_trace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("retrieval_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    memory_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memory_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("memory_versions.id", ondelete="SET NULL"), nullable=True
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "retrieval_trace_id", "memory_id", name="uq_retrieval_decision_trace_memory"
        ),
        CheckConstraint("rank IS NULL OR rank >= 1", name="chk_retrieval_decision_rank"),
        CheckConstraint(
            "injected = 0 OR selected = 1", name="chk_retrieval_decision_injected_selected"
        ),
        CheckConstraint(
            "selected = 0 OR retrieved = 1", name="chk_retrieval_decision_selected_retrieved"
        ),
        Index("ix_retrieval_decisions_owner_trace", "owner_id", "retrieval_trace_id"),
    )


class MemoryUsageModel(Base):
    __tablename__ = "memory_usages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    retrieval_trace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("retrieval_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memory_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memory_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_versions.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    injected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    verification_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_effect: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "run_id",
            "memory_id",
            "memory_version_id",
            name="uq_memory_usage_owner_run_memory_version",
        ),
        CheckConstraint("rank >= 1", name="chk_memory_usage_rank"),
        CheckConstraint("estimated_tokens >= 0", name="chk_memory_usage_tokens"),
        CheckConstraint("selected = 1 AND retrieved = 1", name="chk_memory_usage_selected"),
        CheckConstraint(
            "verification_status IN "
            "('pending', 'applied', 'violated', 'not_observable', 'unknown')",
            name="chk_memory_usage_verification_status",
        ),
        CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_substring', 'structured_provider')",
            name="chk_memory_usage_verification_method",
        ),
        CheckConstraint(
            "user_effect IS NULL OR user_effect IN ('helpful', 'harmful', 'stale')",
            name="chk_memory_usage_user_effect",
        ),
        Index("ix_memory_usages_owner_trace", "owner_id", "retrieval_trace_id"),
        Index("ix_memory_usages_owner_memory", "owner_id", "memory_id"),
    )


class MemoryVerificationJobModel(Base):
    __tablename__ = "memory_verification_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memory_usage_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("memory_usages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="chk_verification_job_status",
        ),
        CheckConstraint("attempt >= 0", name="chk_verification_job_attempt"),
        Index("ix_verification_jobs_owner_status", "owner_id", "status"),
    )


class ImportBatchModel(Base):
    """G4 import batch for Memory Pack two-phase import."""

    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pack_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    format_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="quarantined")
    canonical_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('quarantined', 'committed', 'expired', 'cancelled')",
            name="chk_import_batch_status",
        ),
        CheckConstraint(
            "inserted_count >= 0 AND skipped_count >= 0 AND warning_count >= 0",
            name="chk_import_batch_counts",
        ),
        CheckConstraint(
            "(status = 'committed' AND committed_at IS NOT NULL) OR "
            "(status != 'committed' AND committed_at IS NULL)",
            name="chk_import_batch_committed",
        ),
        UniqueConstraint("preview_token_hash", name="uq_import_batch_preview_token"),
        Index("ix_import_batches_owner", "owner_id"),
        Index("ix_import_batches_expires", "expires_at"),
        Index("ix_import_batches_preview_token_hash", "preview_token_hash"),
    )

    cards: Mapped[list[MemoryCardModel]] = relationship(
        "MemoryCardModel", back_populates="import_batch"
    )


# ===========================================================================
# Day 6 v2 LLM-first memory models
# ===========================================================================


class MemoryEventCursorModel(Base):
    __tablename__ = "memory_event_cursors"

    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    next_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (CheckConstraint("next_seq >= 1", name="chk_memory_event_cursor_next_seq"),)


class MemoryReflectionJobModel(Base):
    __tablename__ = "memory_reflection_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    assistant_message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mutation_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="2.0")
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="chk_reflection_job_status",
        ),
        CheckConstraint("attempt >= 0", name="chk_reflection_job_attempt"),
        CheckConstraint("turn_index >= 1", name="chk_reflection_job_turn_index"),
        CheckConstraint("schema_version = '2.0'", name="chk_reflection_job_schema_version"),
        CheckConstraint(
            "token_source IS NULL OR token_source IN ('actual', 'mock')",
            name="chk_reflection_job_token_source",
        ),
        ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["owner_id", "task_id"],
            ["tasks.owner_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "task_id", "run_id"],
            ["agent_runs.owner_id", "agent_runs.task_id", "agent_runs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "user_message_id"],
            ["messages.owner_id", "messages.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "assistant_message_id"],
            ["messages.owner_id", "messages.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("owner_id", "id", name="uq_reflection_jobs_owner_id"),
        UniqueConstraint(
            "owner_id", "task_id", "run_id", "turn_index", name="uq_reflection_job_turn"
        ),
        Index("ix_reflection_jobs_owner_task", "owner_id", "task_id"),
        Index("ix_reflection_jobs_status_lease", "status", "lease_expires_at", "created_at"),
    )


class MemoryLLMJudgeModel(Base):
    __tablename__ = "memory_llm_judgments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    judge_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="2.0")
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_source: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "judge_type IN ('summary', 'applicability', 'effect', 'consolidation')",
            name="chk_llm_judge_type",
        ),
        CheckConstraint("status IN ('completed', 'failed')", name="chk_llm_judge_status"),
        CheckConstraint("token_source IN ('actual', 'mock')", name="chk_llm_judge_token_source"),
        ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["owner_id", "task_id"],
            ["tasks.owner_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "task_id", "run_id"],
            ["agent_runs.owner_id", "agent_runs.task_id", "agent_runs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "job_id"],
            ["memory_reflection_jobs.owner_id", "memory_reflection_jobs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "memory_id"],
            ["memory_cards.owner_id", "memory_cards.id"],
            ondelete="SET NULL",
        ),
        UniqueConstraint(
            "owner_id",
            "task_id",
            "run_id",
            "memory_id",
            "judge_type",
            name="uq_llm_judge_run_memory_type",
        ),
        Index("ix_llm_judgments_owner_job", "owner_id", "job_id"),
        Index("ix_llm_judgments_owner_memory", "owner_id", "memory_id", "judge_type"),
    )
