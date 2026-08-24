"""G2 memory admission schema

Revision ID: 002_g2_memory_admission
Revises: 001_initial_g1_schema
Create Date: 2026-08-23 00:00:00.000000

Adds memory_cards, memory_versions, memory_evidence, memory_evidence_links,
and memory_relations, and extends memory_jobs with the G2 disposition column
and the expanded five-stage pipeline check.

SQLite cannot ALTER a CHECK constraint, so memory_jobs is rebuilt explicitly
(column list is fully specified) instead of using batch_alter_table, whose
reflection would silently drop the existing status/type checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_g2_memory_admission"
down_revision: str | None = "001_initial_g1_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEMORY_JOB_COLUMNS = (
    "id",
    "owner_id",
    "job_type",
    "feedback_id",
    "status",
    "stage",
    "attempt",
    "last_error_code",
    "created_at",
    "updated_at",
)

_JOB_STATUS_CHECK = "status IN ('pending', 'running', 'completed', 'failed')"
_JOB_STAGE_G1_CHECK = "stage IN ('queued', 'extracting', 'done', 'failed')"
_JOB_STAGE_G2_CHECK = (
    "stage IN ('queued', 'diffing', 'classifying_durability', 'extracting', "
    "'validating', 'admitting', 'done', 'failed')"
)
_JOB_DISPOSITION_CHECK = (
    "disposition IS NULL OR disposition IN "
    "('candidate_created', 'episode_only', 'reinforce_usage_only', 'no_memory', 'failed')"
)


def _rebuild_memory_jobs(new: bool) -> None:
    """Rebuild memory_jobs with (new=True) or without (new=False) the G2 columns."""
    suffix = "new" if new else "old"
    g2_columns = (sa.Column("disposition", sa.String(length=32), nullable=True),) if new else ()
    g2_checks = (
        (sa.CheckConstraint(_JOB_DISPOSITION_CHECK, name="chk_job_disposition"),) if new else ()
    )
    op.create_table(
        f"memory_jobs_{suffix}",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("feedback_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        *g2_columns,
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("job_type IN ('extract_feedback')", name="chk_job_type"),
        sa.CheckConstraint(_JOB_STATUS_CHECK, name="chk_job_status"),
        sa.CheckConstraint(
            _JOB_STAGE_G2_CHECK if new else _JOB_STAGE_G1_CHECK,
            name="chk_job_stage",
        ),
        *g2_checks,
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feedback_id"),
    )
    g1_columns = ", ".join(_MEMORY_JOB_COLUMNS)
    if new:
        # Upgrade: source (G1) has no disposition column; seed it as NULL.
        op.execute(
            f"INSERT INTO memory_jobs_new ({g1_columns}, disposition) "
            f"SELECT {g1_columns}, NULL FROM memory_jobs"
        )
    else:
        # Downgrade: source (G2) disposition is dropped along with the column.
        op.execute(
            f"INSERT INTO memory_jobs_old ({g1_columns}) SELECT {g1_columns} FROM memory_jobs"
        )
    op.drop_table("memory_jobs")
    op.rename_table(f"memory_jobs_{suffix}", "memory_jobs")
    op.create_index(op.f("ix_memory_jobs_owner_id"), "memory_jobs", ["owner_id"], unique=False)


def upgrade() -> None:
    # 1. memory_cards -------------------------------------------------------
    op.create_table(
        "memory_cards",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("memory_job_id", sa.String(length=64), nullable=True),
        # current_version_id intentionally has no FK: cards and versions
        # reference each other and SQLite cannot ADD CONSTRAINT after the
        # fact. The pair is updated in one transaction by the resolve path.
        sa.Column("current_version_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("save_preselected", sa.Boolean(), nullable=False),
        sa.Column("rejection_reason", sa.String(length=32), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("avoid", sa.Text(), nullable=False),
        sa.Column("trigger_text", sa.Text(), nullable=False),
        sa.Column("scope_level", sa.String(length=32), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=True),
        sa.Column("artifact_type", sa.String(length=32), nullable=True),
        sa.Column("audience", sa.String(length=32), nullable=True),
        sa.Column("project_key", sa.String(length=128), nullable=True),
        sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("exceptions_json", sa.Text(), nullable=False),
        sa.Column("source_trust", sa.Float(), nullable=False),
        sa.Column("rule_confidence", sa.Float(), nullable=True),
        sa.Column("scope_confidence", sa.Float(), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('candidate', 'active', 'rejected', 'conflicted', 'paused', "
            "'superseded', 'merged', 'archived', 'deleted')",
            name="chk_memory_card_status",
        ),
        sa.CheckConstraint(
            "kind IN ('preference', 'constraint', 'procedure', 'experience', "
            "'environment', 'learning_checkpoint')",
            name="chk_memory_card_kind",
        ),
        sa.CheckConstraint(
            "source_type IN ('explicit_feedback', 'explicit_correction', 'edit_diff', "
            "'accept', 'reject', 'rating', 'outcome', 'import')",
            name="chk_memory_card_source_type",
        ),
        sa.CheckConstraint(
            "rejection_reason IS NULL OR rejection_reason IN ('user_rejected', 'episode_only')",
            name="chk_memory_card_rejection_reason",
        ),
        sa.CheckConstraint(
            "scope_level IN ('session', 'task_family', 'project', 'global')",
            name="chk_memory_card_scope_level",
        ),
        sa.CheckConstraint(
            "domain IN ('programming_learning', 'software_development', "
            "'general_text', 'other', 'any')",
            name="chk_memory_card_domain",
        ),
        sa.CheckConstraint(
            "task_type IS NULL OR task_type IN ('debugging_guidance', 'code_review', "
            "'code_explanation', 'code_generation', 'environment_configuration', "
            "'general_question', 'other')",
            name="chk_memory_card_task_type",
        ),
        sa.CheckConstraint(
            "artifact_type IS NULL OR artifact_type IN ('source_code', "
            "'configuration', 'text', 'none', 'other')",
            name="chk_memory_card_artifact_type",
        ),
        sa.CheckConstraint(
            "audience IS NULL OR audience IN ('beginner', 'intermediate', 'advanced', 'unknown')",
            name="chk_memory_card_audience",
        ),
        sa.CheckConstraint(
            "status != 'candidate' OR (version = 0 AND current_version_id IS NULL "
            "AND rule_confidence IS NULL AND scope_confidence IS NULL)",
            name="chk_memory_card_candidate_invariants",
        ),
        sa.CheckConstraint(
            "status != 'active' OR (version >= 1 AND current_version_id IS NOT NULL "
            "AND rule_confidence IS NOT NULL AND scope_confidence IS NOT NULL)",
            name="chk_memory_card_active_invariants",
        ),
        sa.CheckConstraint("source_trust >= 0 AND source_trust <= 1", name="chk_memory_card_trust"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_job_id"], ["memory_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_cards_owner_status", "memory_cards", ["owner_id", "status"], unique=False
    )
    op.create_index(
        "ix_memory_cards_owner_status_scope",
        "memory_cards",
        ["owner_id", "status", "domain", "task_type", "project_key"],
        unique=False,
    )
    op.create_index("ix_memory_cards_job", "memory_cards", ["memory_job_id"], unique=False)
    op.create_index(
        "ix_memory_cards_current_version", "memory_cards", ["current_version_id"], unique=False
    )

    # 2. memory_versions ----------------------------------------------------
    op.create_table(
        "memory_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("memory_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("avoid", sa.Text(), nullable=False),
        sa.Column("trigger_text", sa.Text(), nullable=False),
        sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("exceptions_json", sa.Text(), nullable=False),
        sa.Column("created_by_action", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="chk_memory_version_number"),
        sa.CheckConstraint(
            "created_by_action IN ('accept', 'edit_accept')",
            name="chk_memory_version_created_by",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id", "version", name="uq_memory_version_number"),
    )
    op.create_index("ix_memory_versions_memory", "memory_versions", ["memory_id"], unique=False)
    op.create_index("ix_memory_versions_owner", "memory_versions", ["owner_id"], unique=False)

    # 3. memory_evidence ----------------------------------------------------
    op.create_table(
        "memory_evidence",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("feedback_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("memory_job_id", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_field", sa.String(length=32), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("diff_summary_json", sa.Text(), nullable=True),
        sa.Column("normalized_edit_cost", sa.Float(), nullable=True),
        sa.Column("episode_summary", sa.Text(), nullable=True),
        sa.Column("disposition", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('explicit_feedback', 'explicit_correction', 'edit_diff', "
            "'accept', 'reject', 'rating', 'outcome', 'import')",
            name="chk_memory_evidence_source_type",
        ),
        sa.CheckConstraint(
            "source_field IN ('explicit_text', 'edited_output', 'rating', 'accepted')",
            name="chk_memory_evidence_source_field",
        ),
        sa.CheckConstraint(
            "normalized_edit_cost IS NULL OR "
            "(normalized_edit_cost >= 0 AND normalized_edit_cost <= 1)",
            name="chk_memory_evidence_edit_cost",
        ),
        sa.CheckConstraint(
            "disposition IS NULL OR disposition IN "
            "('candidate_created', 'episode_only', 'reinforce_usage_only', "
            "'no_memory', 'failed')",
            name="chk_memory_evidence_disposition",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_job_id"], ["memory_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_evidence_owner", "memory_evidence", ["owner_id"], unique=False)
    op.create_index("ix_memory_evidence_job", "memory_evidence", ["memory_job_id"], unique=False)
    op.create_index("ix_memory_evidence_feedback", "memory_evidence", ["feedback_id"], unique=False)

    # 4. memory_evidence_links ----------------------------------------------
    op.create_table(
        "memory_evidence_links",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("memory_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ordinal >= 0 AND ordinal <= 2", name="chk_evidence_link_ordinal"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["memory_evidence.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id", "evidence_id", name="uq_evidence_link_pair"),
    )
    op.create_index(
        "ix_memory_evidence_links_memory", "memory_evidence_links", ["memory_id"], unique=False
    )

    # 5. memory_relations ---------------------------------------------------
    op.create_table(
        "memory_relations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("from_memory_id", sa.String(length=64), nullable=False),
        sa.Column("to_memory_id", sa.String(length=64), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "relation_type IN ('duplicate_of', 'conflicts_with', 'supersedes', 'related_to')",
            name="chk_memory_relation_type",
        ),
        sa.CheckConstraint("from_memory_id != to_memory_id", name="chk_memory_relation_self"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_memory_id"], ["memory_cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_memory_id"], ["memory_cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_memory_id", "to_memory_id", "relation_type", name="uq_memory_relation_triple"
        ),
    )
    op.create_index(
        "ix_memory_relations_from", "memory_relations", ["from_memory_id"], unique=False
    )
    op.create_index("ix_memory_relations_to", "memory_relations", ["to_memory_id"], unique=False)

    # 6. memory_jobs: add disposition + expand the stage check ---------------
    _rebuild_memory_jobs(new=True)


def downgrade() -> None:
    op.drop_table("memory_relations")
    op.drop_table("memory_evidence_links")
    op.drop_table("memory_evidence")
    op.drop_table("memory_versions")
    op.drop_table("memory_cards")
    _rebuild_memory_jobs(new=False)
