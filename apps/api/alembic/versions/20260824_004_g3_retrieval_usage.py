"""G3 retrieval, usage, verification, and card counters.

Revision ID: 004_g3_retrieval_usage
Revises: 003_g2_job_retryable
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_g3_retrieval_usage"
down_revision: str | None = "003_g2_job_retryable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- retrieval_traces ---
    op.create_table(
        "retrieval_traces",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("retrieval_mode", sa.String(32), nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("top_k", sa.Integer, nullable=False),
        sa.Column("candidate_count", sa.Integer, nullable=False, default=0),
        sa.Column("retrieved_count", sa.Integer, nullable=False, default=0),
        sa.Column("selected_count", sa.Integer, nullable=False, default=0),
        sa.Column("injected_count", sa.Integer, nullable=False, default=0),
        sa.Column("decisions_json", sa.Text, nullable=False, default="[]"),
        sa.Column("retrieval_ms", sa.Integer, nullable=False, default=0),
        sa.Column("memory_chars", sa.Integer, nullable=False, default=0),
        sa.Column("memory_tokens_estimated", sa.Integer, nullable=False, default=0),
        sa.Column("provider_prompt_tokens_actual", sa.Integer, nullable=True),
        sa.Column("prompt_section_hash", sa.String(64), nullable=True),
        sa.Column("reason_codes_json", sa.Text, nullable=False, default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("retrieval_mode IN ('tfidf', 'tfidf_degraded')", name="chk_retrieval_trace_mode"),
        sa.CheckConstraint("retrieval_ms >= 0", name="chk_retrieval_trace_ms"),
        sa.CheckConstraint("threshold >= 0 AND threshold <= 1", name="chk_retrieval_trace_threshold"),
        sa.CheckConstraint("top_k > 0", name="chk_retrieval_trace_top_k"),
        sa.UniqueConstraint("owner_id", "run_id", name="uq_retrieval_trace_owner_run"),
    )
    op.create_index("ix_retrieval_traces_task", "retrieval_traces", ["task_id"])
    op.create_index("ix_retrieval_traces_owner_task", "retrieval_traces", ["owner_id", "task_id"])

    # --- retrieval_decisions ---
    op.create_table(
        "retrieval_decisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("retrieval_trace_id", sa.String(64), sa.ForeignKey("retrieval_traces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("memory_id", sa.String(64), sa.ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("memory_version_id", sa.String(64), sa.ForeignKey("memory_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("memory_status", sa.String(32), nullable=False),
        sa.Column("retrieved", sa.Boolean, nullable=False, default=False),
        sa.Column("selected", sa.Boolean, nullable=False, default=False),
        sa.Column("injected", sa.Boolean, nullable=False, default=False),
        sa.Column("rank", sa.Integer, nullable=True),
        sa.Column("scope_match", sa.Float, nullable=True),
        sa.Column("semantic_similarity", sa.Float, nullable=True),
        sa.Column("provenance_confidence", sa.Float, nullable=True),
        sa.Column("verified_effect", sa.Float, nullable=True),
        sa.Column("recency", sa.Float, nullable=True),
        sa.Column("final_score", sa.Float, nullable=True),
        sa.Column("reason_codes_json", sa.Text, nullable=False, default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "memory_status IN ('candidate', 'active', 'rejected', 'conflicted', "
            "'paused', 'superseded', 'merged', 'archived', 'deleted')",
            name="chk_retrieval_decision_memory_status",
        ),
        sa.CheckConstraint("rank IS NULL OR rank >= 1", name="chk_retrieval_decision_rank"),
        sa.UniqueConstraint("retrieval_trace_id", "memory_id", name="uq_retrieval_decision_trace_memory"),
    )
    op.create_index("ix_retrieval_decisions_trace", "retrieval_decisions", ["retrieval_trace_id"])
    op.create_index("ix_retrieval_decisions_memory", "retrieval_decisions", ["memory_id"])

    # --- memory_usages ---
    op.create_table(
        "memory_usages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("retrieval_trace_id", sa.String(64), sa.ForeignKey("retrieval_traces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("memory_id", sa.String(64), sa.ForeignKey("memory_cards.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("memory_version_id", sa.String(64), sa.ForeignKey("memory_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("retrieved", sa.Boolean, nullable=False, default=True),
        sa.Column("selected", sa.Boolean, nullable=False, default=True),
        sa.Column("injected", sa.Boolean, nullable=False, default=False),
        sa.Column("estimated_tokens", sa.Integer, nullable=False, default=0),
        sa.Column("verification_status", sa.String(32), nullable=False, default="pending"),
        sa.Column("verification_method", sa.String(32), nullable=True),
        sa.Column("evidence_excerpt", sa.Text, nullable=True),
        sa.Column("user_effect", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'applied', 'violated', 'not_observable', 'unknown')",
            name="chk_memory_usage_verification_status",
        ),
        sa.CheckConstraint(
            "verification_method IS NULL OR verification_method IN ('exact_substring', 'structured_provider')",
            name="chk_memory_usage_verification_method",
        ),
        sa.CheckConstraint(
            "user_effect IS NULL OR user_effect IN ('helpful', 'harmful', 'stale')",
            name="chk_memory_usage_user_effect",
        ),
        sa.CheckConstraint("rank >= 1", name="chk_memory_usage_rank"),
        sa.UniqueConstraint(
            "owner_id", "run_id", "memory_id", "memory_version_id",
            name="uq_memory_usage_owner_run_memory_version",
        ),
    )
    op.create_index("ix_memory_usages_trace", "memory_usages", ["retrieval_trace_id"])
    op.create_index("ix_memory_usages_memory", "memory_usages", ["memory_id"])
    op.create_index("ix_memory_usages_owner_run", "memory_usages", ["owner_id", "run_id"])

    # --- memory_verification_jobs ---
    op.create_table(
        "memory_verification_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("memory_usage_id", sa.String(64), sa.ForeignKey("memory_usages.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("status", sa.String(32), nullable=False, default="pending"),
        sa.Column("attempt", sa.Integer, nullable=False, default=0),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="chk_verification_job_status",
        ),
        sa.CheckConstraint("attempt >= 0", name="chk_verification_job_attempt"),
    )

    # --- memory_cards counters ---
    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.add_column(sa.Column("retrieved_count", sa.Integer, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("injected_count", sa.Integer, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("verified_applied_count", sa.Integer, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("helpful_count", sa.Integer, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("harmful_count", sa.Integer, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("stale_count", sa.Integer, nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))

    # --- memory_versions created_by_action extended ---
    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.alter_column(
            "created_by_action",
            existing_type=sa.String(32),
            type_=sa.String(32),
            existing_nullable=False,
        )

    # Drop the old CHECK constraint and add the new one that includes 'edit'
    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.drop_constraint("chk_memory_version_created_by", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_version_created_by",
            "created_by_action IN ('accept', 'edit_accept', 'edit')",
        )


def downgrade() -> None:
    # Reverse memory_versions constraint
    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.drop_constraint("chk_memory_version_created_by", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_version_created_by",
            "created_by_action IN ('accept', 'edit_accept')",
        )

    # Drop memory_cards counter columns
    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.drop_column("retrieved_count")
        batch_op.drop_column("injected_count")
        batch_op.drop_column("verified_applied_count")
        batch_op.drop_column("helpful_count")
        batch_op.drop_column("harmful_count")
        batch_op.drop_column("stale_count")
        batch_op.drop_column("last_used_at")

    # Drop new tables
    op.drop_table("memory_verification_jobs")
    op.drop_table("memory_usages")
    op.drop_table("retrieval_decisions")
    op.drop_table("retrieval_traces")
