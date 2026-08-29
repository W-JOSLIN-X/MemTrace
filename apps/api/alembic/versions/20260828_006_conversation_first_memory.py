"""006_conversation_first_memory: v2 LLM-first memory schema.

Changes:
- memory_reflection_jobs: v2 background reflection job table
- memory_llm_judgments: applicability/effect/consolidation judge records
- memory_cards: v2 columns + 'rule' in kind check
- memory_evidence: message_id FK + nullable FKs for v2 compatibility
- memory_versions: v2 columns
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "006_conversation_first_memory"
down_revision = "005_g4_memory_center_pack"
branch_labels = None
depends_on = None


def _rebuild_memory_cards_add_rule_kind() -> None:
    """Rebuild memory_cards adding 'rule' to the kind check constraint."""
    try:
        op.execute("""
            CREATE TABLE memory_cards_new (
                id VARCHAR(64) PRIMARY KEY,
                owner_id VARCHAR(64) NOT NULL,
                memory_job_id VARCHAR(64),
                current_version_id VARCHAR(64),
                status VARCHAR(32) NOT NULL,
                kind VARCHAR(32),
                source_type VARCHAR(32),
                save_preselected BOOLEAN NOT NULL DEFAULT 0,
                rejection_reason VARCHAR(32),
                content TEXT,
                applies_when TEXT,
                review_status VARCHAR(32),
                confidence FLOAT,
                rule_subtype VARCHAR(32),
                schema_version VARCHAR(16),
                scope_level_legacy VARCHAR(32),
                task_type_legacy VARCHAR(32),
                artifact_type_legacy VARCHAR(32),
                audience_legacy VARCHAR(32),
                project_key_legacy VARCHAR(128),
                language_legacy VARCHAR(32),
                framework_legacy VARCHAR(64),
                title TEXT,
                rule TEXT,
                avoid TEXT DEFAULT '',
                trigger_text TEXT DEFAULT '',
                scope_level VARCHAR(32),
                domain VARCHAR(32),
                task_type VARCHAR(32),
                artifact_type VARCHAR(32),
                audience VARCHAR(32),
                project_key VARCHAR(128),
                scope_json TEXT DEFAULT '{}',
                exceptions_json TEXT DEFAULT '[]',
                source_trust FLOAT,
                rule_confidence FLOAT,
                scope_confidence FLOAT,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 0,
                valid_from DATETIME,
                valid_to DATETIME,
                retrieved_count INTEGER NOT NULL DEFAULT 0,
                injected_count INTEGER NOT NULL DEFAULT 0,
                verified_applied_count INTEGER NOT NULL DEFAULT 0,
                helpful_count INTEGER NOT NULL DEFAULT 0,
                harmful_count INTEGER NOT NULL DEFAULT 0,
                stale_count INTEGER NOT NULL DEFAULT 0,
                last_used_at DATETIME,
                evidence_missing BOOLEAN NOT NULL DEFAULT 0,
                deleted_at DATETIME,
                import_batch_id VARCHAR(64),
                import_source_version INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CHECK (status IN ('candidate', 'active', 'rejected', 'conflicted', 'paused',
                    'superseded', 'merged', 'archived', 'deleted')),
                CHECK (kind IN ('preference', 'constraint', 'procedure', 'experience',
                    'environment', 'learning_checkpoint', 'rule')),
                CHECK (rejection_reason IS NULL OR rejection_reason IN (
                    'user_rejected', 'episode_only')),
                CHECK ((rejection_reason IS NULL AND status != 'rejected') OR
                    (rejection_reason IS NOT NULL AND status = 'rejected')),
                CHECK ((status IN ('active', 'paused')) OR
                    (current_version_id IS NULL AND version = 0)),
                FOREIGN KEY (memory_job_id) REFERENCES memory_jobs(id),
                FOREIGN KEY (import_batch_id) REFERENCES import_batches(id)
            )
        """)
        op.execute("""
            INSERT INTO memory_cards_new
            SELECT id, owner_id, memory_job_id, current_version_id, status, kind,
                source_type, save_preselected, rejection_reason, content, applies_when,
                review_status, confidence, rule_subtype, schema_version,
                scope_level_legacy, task_type_legacy, artifact_type_legacy,
                audience_legacy, project_key_legacy, language_legacy, framework_legacy,
                title, rule, avoid, trigger_text, scope_level, domain, task_type,
                artifact_type, audience, project_key, scope_json, exceptions_json,
                source_trust, rule_confidence, scope_confidence, evidence_count,
                version, valid_from, valid_to, retrieved_count, injected_count,
                verified_applied_count, helpful_count, harmful_count, stale_count,
                last_used_at, evidence_missing, deleted_at, import_batch_id,
                import_source_version, created_at, updated_at
            FROM memory_cards
        """)
        op.execute("DROP TABLE memory_cards")
        op.execute("ALTER TABLE memory_cards_new RENAME TO memory_cards")
    except Exception:
        op.execute("DROP TABLE IF EXISTS memory_cards_new")
        raise


def _rebuild_memory_cards_remove_rule_kind() -> None:
    """Rebuild memory_cards removing 'rule' from kind check constraint on downgrade."""
    try:
        op.execute("""
            CREATE TABLE memory_cards_new (
                id VARCHAR(64) PRIMARY KEY,
                owner_id VARCHAR(64) NOT NULL,
                memory_job_id VARCHAR(64),
                current_version_id VARCHAR(64),
                status VARCHAR(32) NOT NULL,
                kind VARCHAR(32),
                source_type VARCHAR(32),
                save_preselected BOOLEAN NOT NULL DEFAULT 0,
                rejection_reason VARCHAR(32),
                content TEXT,
                applies_when TEXT,
                review_status VARCHAR(32),
                confidence FLOAT,
                rule_subtype VARCHAR(32),
                schema_version VARCHAR(16),
                scope_level_legacy VARCHAR(32),
                task_type_legacy VARCHAR(32),
                artifact_type_legacy VARCHAR(32),
                audience_legacy VARCHAR(32),
                project_key_legacy VARCHAR(128),
                language_legacy VARCHAR(32),
                framework_legacy VARCHAR(64),
                title TEXT,
                rule TEXT,
                avoid TEXT DEFAULT '',
                trigger_text TEXT DEFAULT '',
                scope_level VARCHAR(32),
                domain VARCHAR(32),
                task_type VARCHAR(32),
                artifact_type VARCHAR(32),
                audience VARCHAR(32),
                project_key VARCHAR(128),
                scope_json TEXT DEFAULT '{}',
                exceptions_json TEXT DEFAULT '[]',
                source_trust FLOAT,
                rule_confidence FLOAT,
                scope_confidence FLOAT,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 0,
                valid_from DATETIME,
                valid_to DATETIME,
                retrieved_count INTEGER NOT NULL DEFAULT 0,
                injected_count INTEGER NOT NULL DEFAULT 0,
                verified_applied_count INTEGER NOT NULL DEFAULT 0,
                helpful_count INTEGER NOT NULL DEFAULT 0,
                harmful_count INTEGER NOT NULL DEFAULT 0,
                stale_count INTEGER NOT NULL DEFAULT 0,
                last_used_at DATETIME,
                evidence_missing BOOLEAN NOT NULL DEFAULT 0,
                deleted_at DATETIME,
                import_batch_id VARCHAR(64),
                import_source_version INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CHECK (status IN ('candidate', 'active', 'rejected', 'conflicted', 'paused',
                    'superseded', 'merged', 'archived', 'deleted')),
                CHECK (kind IN ('preference', 'constraint', 'procedure', 'experience',
                    'environment', 'learning_checkpoint')),
                CHECK (rejection_reason IS NULL OR rejection_reason IN (
                    'user_rejected', 'episode_only')),
                CHECK ((rejection_reason IS NULL AND status != 'rejected') OR
                    (rejection_reason IS NOT NULL AND status = 'rejected')),
                CHECK ((status IN ('active', 'paused')) OR
                    (current_version_id IS NULL AND version = 0)),
                FOREIGN KEY (memory_job_id) REFERENCES memory_jobs(id),
                FOREIGN KEY (import_batch_id) REFERENCES import_batches(id)
            )
        """)
        op.execute("""
            INSERT INTO memory_cards_new
            SELECT * FROM memory_cards
        """)
        op.execute("DROP TABLE memory_cards")
        op.execute("ALTER TABLE memory_cards_new RENAME TO memory_cards")
    except Exception:
        op.execute("DROP TABLE IF EXISTS memory_cards_new")
        raise


def upgrade() -> None:
    # =========================================================================
    # 1. memory_cards: v2-only new columns
    # =========================================================================
    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.add_column(sa.Column("content", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("applies_when", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("review_status", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("rule_subtype", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("schema_version", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("scope_level_legacy", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("task_type_legacy", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("artifact_type_legacy", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("audience_legacy", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("project_key_legacy", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("language_legacy", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("framework_legacy", sa.String(64), nullable=True))

    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.create_index("ix_memory_cards_review_status", ["review_status"], unique=False)
        batch_op.create_index("ix_memory_cards_confidence", ["confidence"], unique=False)

    # =========================================================================
    # 2. memory_versions: v2 columns + extend created_by_action check
    # =========================================================================
    # SQLite cannot ALTER CHECK constraints, so we rebuild the table
    # to add v2 created_by_action values (llm_extract, llm_update, llm_supersede).
    _rebuild_memory_versions_with_v2_actions()

    # =========================================================================
    # 3. memory_evidence: v2 columns (message_id FK)
    # =========================================================================
    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.add_column(sa.Column("message_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("turn_index", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_primary", sa.Boolean(), nullable=True, server_default="1"))
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
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mutation_decision", sa.String(32), nullable=True),
        sa.Column("provider_model", sa.String(128), nullable=True),
        sa.Column("prompt_hash", sa.String(64), nullable=True),
        sa.Column("schema_version", sa.String(16), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="chk_reflection_job_status"),
        sa.CheckConstraint("attempt >= 0", name="chk_reflection_job_attempt"),
        sa.CheckConstraint("turn_index >= 0", name="chk_reflection_job_turn_index"),
        sa.CheckConstraint("schema_version = '2.0'", name="chk_reflection_job_schema_version"),
        sa.UniqueConstraint("id", "owner_id", name="uq_reflection_job_id_owner"),
        sa.Index("ix_reflection_jobs_owner", "owner_id"),
        sa.Index("ix_reflection_jobs_task", "task_id"),
        sa.Index("ix_reflection_jobs_status", "status"),
    )

    # =========================================================================
    # 5. NEW TABLE: memory_llm_judgments
    # =========================================================================
    op.create_table(
        "memory_llm_judgments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("memory_reflection_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_id", sa.String(64), sa.ForeignKey("memory_cards.id", ondelete="SET NULL"), nullable=True),
        sa.Column("judge_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("provider_model", sa.String(128), nullable=True),
        sa.Column("prompt_hash", sa.String(64), nullable=True),
        sa.Column("schema_version", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "judge_type IN ('applicability', 'effect', 'consolidation')",
            name="chk_llm_judge_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="chk_llm_judge_status",
        ),
        sa.Index("ix_llm_judges_job", "job_id"),
        sa.Index("ix_llm_judges_memory", "memory_id"),
    )

    # =========================================================================
    # 6. memory_cards: add 'rule' to kind check constraint (via table rebuild)
    # =========================================================================
    _rebuild_memory_cards_add_rule_kind()

    # =========================================================================
    # 7. memory_evidence: add consolidation evidence columns
    # =========================================================================
    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.add_column(sa.Column("consolidation_decision", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("consolidation_confidence", sa.Float(), nullable=True))

    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")

    try:
        op.execute("DELETE FROM memory_cards WHERE review_status = 'legacy_unverified'")
    except Exception:
        pass

    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.drop_column("consolidation_confidence")
        batch_op.drop_column("consolidation_decision")

    with op.batch_alter_table("memory_relations") as batch_op:
        batch_op.drop_column("consolidation_decided_at")
        batch_op.drop_column("consolidation_confidence")
        batch_op.drop_column("llm_consolidation_decision")

    op.drop_table("memory_llm_judgments")
    op.drop_table("memory_reflection_jobs")

    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.drop_column("is_primary")
        batch_op.drop_column("turn_index")
        batch_op.drop_column("message_id")

    _rebuild_memory_versions_remove_v2_actions()

    _rebuild_memory_cards_remove_rule_kind()

    try:
        with op.batch_alter_table("memory_cards") as batch_op:
            batch_op.drop_index("ix_memory_cards_confidence")
            batch_op.drop_index("ix_memory_cards_review_status")
            batch_op.drop_column("schema_version")
            batch_op.drop_column("rule_subtype")
            batch_op.drop_column("confidence")
            batch_op.drop_column("review_status")
            batch_op.drop_column("applies_when")
            batch_op.drop_column("content")
    except Exception:
        pass
