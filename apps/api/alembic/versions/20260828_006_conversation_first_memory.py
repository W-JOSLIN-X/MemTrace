"""Day 6 2.0.0: Conversation-first memory — reflection jobs, LLM judgments, v2 card fields.

Revision ID: 006_conversation_first_memory
Revises: 005_g4_memory_center_pack
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006_conversation_first_memory"
down_revision: str | None = "005_g4_memory_center_pack"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---- helpers ----

def _fk(table: str, column: str, ref_table: str, ref_column: str, ondelete: str = "CASCADE") -> None:
    op.create_foreign_key(
        f"fk_{table}_{column}",
        table,
        ref_table,
        [column],
        [ref_column],
        ondelete=ondelete,
    )


def _index(table: str, columns: list[str], name: str | None = None) -> None:
    idx = name or f"ix_{table}_{'_'.join(columns)}"
    op.create_index(idx, table, columns)


def _check(table: str, name: str, expr: str) -> None:
    op.create_check_constraint(name, table, expr)


def _drop_if_exists(table: str, kind: str, name: str) -> None:
    """Safely drop constraint/index if it exists (SQLite requires existence check)."""
    try:
        if kind == "check":
            op.drop_constraint(name, table, type_="check")
        elif kind == "foreignkey":
            op.drop_constraint(name, table, type_="foreignkey")
        elif kind == "unique":
            op.drop_constraint(name, table, type_="unique")
        elif kind == "index":
            op.drop_index(name, table)
    except Exception:
        pass


def upgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")

    # =========================================================================
    # 1. memory_cards: v2-only new columns
    # =========================================================================
    # G4 (005) already added: deleted_at/deleted_by/deletion_reason,
    #   evidence_missing, import_batch_id, import_source_version,
    #   status (nullability change), and set existing columns to nullable.
    # G2 (002) already added: valid_from, valid_to, scope_level, domain,
    #   scope_json, exceptions_json, source_trust.
    # This batch_alter_table only adds NEW columns that do NOT yet exist.
    with op.batch_alter_table("memory_cards") as batch_op:
        # v2 primary fields (all new, not in G2/G4)
        batch_op.add_column(
            sa.Column("content", sa.Text(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("applies_when", sa.Text(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("review_status", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("confidence", sa.Float(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("rule_subtype", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("schema_version", sa.String(16), nullable=True),
        )
        # Legacy scope columns (mirror existing G2/G4 structured scope; preserved for compatibility)
        # NOTE: scope_level, domain, scope_json, exceptions_json, source_trust already exist from G2.
        # These _legacy columns provide read-only copies for v1→v2 compatibility projections.
        batch_op.add_column(
            sa.Column("scope_level_legacy", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("task_type_legacy", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("artifact_type_legacy", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("audience_legacy", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("project_key_legacy", sa.String(128), nullable=True),
        )
        batch_op.add_column(
            sa.Column("language_legacy", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("framework_legacy", sa.String(64), nullable=True),
        )

        # New indexes
        batch_op.create_index(
            "ix_memory_cards_review_status",
            ["review_status"],
        )
        batch_op.create_index(
            "ix_memory_cards_confidence",
            ["confidence"],
        )

    # Update G4 content-state check: v2 cards use content/applies_when; deleted keeps nulls
    # SQLite batch mode requires checks inside batch_alter_table
    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.drop_constraint("chk_memory_card_g4_content_state", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_card_v2_content_state",
            "(status = 'deleted' AND kind IS NULL AND source_type IS NULL "
            "AND content IS NULL AND applies_when IS NULL AND review_status IS NULL "
            "AND current_version_id IS NULL AND version = 0 "
            "AND retrieved_count = 0 AND injected_count = 0 "
            "AND verified_applied_count = 0 AND helpful_count = 0 "
            "AND harmful_count = 0 AND stale_count = 0) OR "
            "(status != 'deleted' AND kind IS NOT NULL AND source_type IS NOT NULL "
            "AND content IS NOT NULL AND applies_when IS NOT NULL "
            "AND review_status IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "chk_memory_card_review_status",
            "review_status IN ('active', 'review', 'paused', 'archived', 'superseded')",
        )
        batch_op.create_check_constraint(
            "chk_memory_card_confidence",
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
        )
        batch_op.create_check_constraint(
            "chk_memory_card_validity_range",
            "(valid_from IS NULL AND valid_to IS NULL) OR "
            "(valid_from IS NOT NULL AND "
            "(valid_to IS NULL OR valid_to > valid_from))",
        )
        batch_op.create_check_constraint(
            "chk_memory_card_rule_subtype",
            "rule_subtype IS NULL OR rule_subtype IN ('constraint', 'procedure')",
        )

    # =========================================================================
    # 2. memory_versions: v2 content fields
    # =========================================================================
    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.add_column(
            sa.Column("content", sa.Text(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("applies_when", sa.Text(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("confidence", sa.Float(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("review_status", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("rule_subtype", sa.String(32), nullable=True),
        )
        batch_op.drop_constraint("chk_memory_version_created_by", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_version_created_by_v2",
            "created_by_action IN ('accept', 'edit_accept', 'edit', 'import', "
            "'merge', 'scope_resolution', 'llm_extract', 'llm_update', 'llm_supersede')",
        )
        batch_op.create_check_constraint(
            "chk_memory_version_v2_content",
            "(created_by_action IN ('accept', 'edit_accept', 'edit', 'llm_extract', 'llm_update') "
            "AND content IS NOT NULL AND applies_when IS NOT NULL) OR "
            "(created_by_action NOT IN ('accept', 'edit_accept', 'edit', 'llm_extract', 'llm_update') "
            "AND content IS NULL AND applies_when IS NULL)",
        )

    # =========================================================================
    # 3. memory_evidence: add message_id FK for v2 evidence chain
    # =========================================================================
    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.add_column(
            sa.Column("message_id", sa.String(64), nullable=True),
        )
        batch_op.add_column(
            sa.Column("turn_index", sa.Integer(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("is_primary", sa.Boolean(), nullable=True, server_default="1"),
        )
        batch_op.create_check_constraint(
            "chk_memory_evidence_message_consistency",
            "(message_id IS NULL AND feedback_id IS NOT NULL) OR "
            "(message_id IS NOT NULL AND feedback_id IS NULL) OR "
            "(message_id IS NOT NULL AND feedback_id IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "chk_memory_evidence_turn_index",
            "turn_index IS NULL OR turn_index >= 0",
        )

    # =========================================================================
    # 4. NEW TABLE: memory_reflection_jobs
    # =========================================================================
    op.create_table(
        "memory_reflection_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.String(64),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mutation_decision", sa.String(32), nullable=True),
        sa.Column("provider_model", sa.String(128), nullable=True),
        sa.Column("prompt_hash", sa.String(64), nullable=True),
        sa.Column("schema_version", sa.String(16), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="chk_reflection_job_status",
        ),
        sa.CheckConstraint(
            "attempt >= 0",
            name="chk_reflection_job_attempt",
        ),
        sa.CheckConstraint(
            "turn_index >= 0",
            name="chk_reflection_job_turn_index",
        ),
        sa.CheckConstraint(
            "schema_version = '2.0'",
            name="chk_reflection_job_schema_version",
        ),
        sa.UniqueConstraint("owner_id", "task_id", "run_id", "turn_index", name="uq_reflection_job_turn"),
    )
    _index("memory_reflection_jobs", ["owner_id", "task_id"])
    _index("memory_reflection_jobs", ["status"])
    _index("memory_reflection_jobs", ["owner_id", "status"])

    # =========================================================================
    # 5. NEW TABLE: memory_llm_judgments
    # =========================================================================
    op.create_table(
        "memory_llm_judgments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("memory_reflection_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id",
            sa.String(64),
            sa.ForeignKey("memory_cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("judge_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "judge_type IN ('applicability', 'effect', 'consolidation')",
            name="chk_llm_judge_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="chk_llm_judge_status",
        ),
        sa.UniqueConstraint("job_id", "judge_type", name="uq_llm_judge_job_type"),
    )
    _index("memory_llm_judgments", ["owner_id", "job_id"])
    _index("memory_llm_judgments", ["memory_id"])
    _index("memory_llm_judgments", ["judge_type", "status"])

    # =========================================================================
    # 6. memory_relations: add LLM consolidation fields
    # =========================================================================
    with op.batch_alter_table("memory_relations") as batch_op:
        batch_op.add_column(
            sa.Column("llm_consolidation_decision", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("consolidation_confidence", sa.Float(), nullable=True),
        )
        batch_op.add_column(
            sa.Column(
                "consolidation_decided_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        batch_op.drop_constraint("chk_memory_relation_type", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_relation_type_v2",
            "relation_type IN ('duplicate_of', 'conflicts_with', 'supersedes', "
            "'reinforces', 'merged_into', 'related_to')",
        )
        batch_op.create_check_constraint(
            "chk_memory_relation_consolidation",
            "llm_consolidation_decision IS NULL OR "
            "llm_consolidation_decision IN ('duplicate', 'update', 'supersede', 'coexist', 'review')",
        )
        batch_op.create_check_constraint(
            "chk_memory_relation_consolidation_confidence",
            "consolidation_confidence IS NULL OR "
            "(consolidation_confidence >= 0.0 AND consolidation_confidence <= 1.0)",
        )

    # =========================================================================
    # 7. memory_evidence: add consolidation evidence columns
    # =========================================================================
    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.add_column(
            sa.Column("consolidation_decision", sa.String(32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("consolidation_confidence", sa.Float(), nullable=True),
        )

    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")

    # Only delete legacy_unverified rows on downgrade; never touch active/confirmed data
    # (quarantine rows from migration data corrections are safe to remove)
    try:
        op.execute(
            "DELETE FROM memory_cards WHERE review_status = 'legacy_unverified'"
        )
    except Exception:
        pass

    # ---- memory_evidence cleanup ----
    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.drop_column("consolidation_confidence")
        batch_op.drop_column("consolidation_decision")

    # ---- memory_relations cleanup ----
    with op.batch_alter_table("memory_relations") as batch_op:
        batch_op.drop_column("consolidation_decided_at")
        batch_op.drop_column("consolidation_confidence")
        batch_op.drop_column("llm_consolidation_decision")

    # ---- Drop new tables ----
    op.drop_table("memory_llm_judgments")
    op.drop_table("memory_reflection_jobs")

    # ---- memory_evidence rollback ----
    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.drop_column("is_primary")
        batch_op.drop_column("turn_index")
        batch_op.drop_column("message_id")

    # ---- memory_versions rollback ----
    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.drop_column("rule_subtype")
        batch_op.drop_column("review_status")
        batch_op.drop_column("confidence")
        batch_op.drop_column("applies_when")
        batch_op.drop_column("content")

    # ---- memory_cards rollback ----
    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.drop_index("ix_memory_cards_confidence")
        batch_op.drop_index("ix_memory_cards_review_status")
        batch_op.drop_column("framework_legacy")
        batch_op.drop_column("language_legacy")
        batch_op.drop_column("project_key_legacy")
        batch_op.drop_column("audience_legacy")
        batch_op.drop_column("artifact_type_legacy")
        batch_op.drop_column("task_type_legacy")
        batch_op.drop_column("scope_level_legacy")
        batch_op.drop_column("schema_version")
        batch_op.drop_column("rule_subtype")
        batch_op.drop_column("valid_to")
        batch_op.drop_column("valid_from")
        batch_op.drop_column("confidence")
        batch_op.drop_column("review_status")
        batch_op.drop_column("applies_when")
        batch_op.drop_column("content")

    # Restore G4 content-state check
    _check(
        "memory_cards",
        "chk_memory_card_g4_content_state",
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
    )
    _drop_if_exists("memory_cards", "check", "chk_memory_card_v2_content_state")
    _drop_if_exists("memory_cards", "check", "chk_memory_card_review_status")
    _drop_if_exists("memory_cards", "check", "chk_memory_card_confidence")
    _drop_if_exists("memory_cards", "check", "chk_memory_card_validity_range")
    _drop_if_exists("memory_cards", "check", "chk_memory_card_rule_subtype")
    _drop_if_exists("memory_cards", "check", "chk_memory_card_v2_content_state")

    # Restore memory_versions check
    _drop_if_exists("memory_versions", "check", "chk_memory_version_v2_content")
    _check(
        "memory_versions",
        "chk_memory_version_created_by",
        "created_by_action IN ('accept', 'edit_accept', 'edit')",
    )

    # Restore memory_evidence check
    _drop_if_exists("memory_evidence", "check", "chk_memory_evidence_message_consistency")
    _drop_if_exists("memory_evidence", "check", "chk_memory_evidence_turn_index")

    # Restore memory_relations check
    _drop_if_exists("memory_relations", "check", "chk_memory_relation_type_v2")
    _drop_if_exists("memory_relations", "check", "chk_memory_relation_consolidation")
    _drop_if_exists("memory_relations", "check", "chk_memory_relation_consolidation_confidence")

    # Restore memory_relation_type
    _drop_if_exists("memory_relations", "check", "chk_memory_relation_type")
    _check(
        "memory_relations",
        "chk_memory_relation_type",
        "relation_type IN ('duplicate_of', 'conflicts_with', 'supersedes', 'related_to')",
    )

    op.execute("PRAGMA foreign_keys=ON")
