"""Conversation-first, LLM-driven memory schema.

Revision ID: 006_conversation_first_memory
Revises: 005_g4_memory_center_pack
Create Date: 2026-08-28

G1-G4 columns remain intact for compatibility. G5 adds a separate semantic
kind/lifecycle, conversation turn metadata, durable worker leases, per-card
LLM judgments, actual usage, and an owner-scoped memory event cursor.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006_conversation_first_memory"
down_revision: str | None = "005_g4_memory_center_pack"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite batch operations rebuild parent tables. Keep FK enforcement off
    # so temporary source-table drops cannot cascade into existing G1-G4 rows.
    op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("conversation_summary", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("summary_through_turn", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("next_turn_index", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.create_check_constraint(
            "chk_task_conversation_cursors",
            "summary_through_turn >= 0 AND next_turn_index >= 1",
        )
        batch_op.create_unique_constraint("uq_tasks_owner_id", ["owner_id", "id"])

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(sa.Column("total_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reasoning_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("provider_response_id", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("prompt_hash", sa.String(71), nullable=True))
        batch_op.add_column(sa.Column("schema_version", sa.String(16), nullable=True))
        batch_op.create_check_constraint(
            "chk_run_extended_usage",
            "(total_tokens IS NULL OR total_tokens >= 0) AND "
            "(reasoning_tokens IS NULL OR reasoning_tokens >= 0)",
        )
        batch_op.create_unique_constraint(
            "uq_agent_runs_owner_task_id", ["owner_id", "task_id", "id"]
        )

    with op.batch_alter_table("retrieval_traces") as batch_op:
        batch_op.drop_constraint("chk_retrieval_trace_mode", type_="check")
        batch_op.create_check_constraint(
            "chk_retrieval_trace_mode",
            "retrieval_mode IN ('tfidf', 'tfidf_degraded', 'llm_judge')",
        )

    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("turn_index", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "chk_message_turn_index", "turn_index IS NULL OR turn_index >= 1"
        )
        batch_op.create_unique_constraint("uq_messages_owner_id", ["owner_id", "id"])
        batch_op.create_index(
            "ix_messages_owner_task_turn", ["owner_id", "task_id", "turn_index", "role"]
        )

    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.add_column(sa.Column("memory_kind_v2", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("content", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("applies_when", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("review_status", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("rule_subtype", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("schema_version", sa.String(16), nullable=True))
        batch_op.drop_constraint("chk_memory_card_status", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_card_status",
            "status IN ('candidate', 'pending', 'active', 'rejected', 'conflicted', "
            "'paused', 'superseded', 'merged', 'archived', 'deleted')",
        )
        batch_op.drop_constraint("chk_memory_card_source_type", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_card_source_type",
            "source_type IS NULL OR source_type IN ('explicit_feedback', "
            "'explicit_correction', 'edit_diff', 'accept', 'reject', 'rating', "
            "'outcome', 'import', 'conversation_turn', 'user_edit')",
        )
        batch_op.create_check_constraint(
            "chk_memory_card_v2_kind",
            "memory_kind_v2 IS NULL OR memory_kind_v2 IN ('preference', 'rule', 'experience')",
        )
        batch_op.create_check_constraint(
            "chk_memory_card_review_status",
            "review_status IS NULL OR review_status IN "
            "('active', 'pending', 'paused', 'archived', 'superseded', "
            "'legacy_unverified')",
        )
        batch_op.create_check_constraint(
            "chk_memory_card_v2_confidence",
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
        )
        batch_op.create_check_constraint(
            "chk_memory_card_rule_subtype",
            "rule_subtype IS NULL OR rule_subtype IN ('constraint', 'procedure')",
        )
        batch_op.create_check_constraint(
            "chk_memory_card_v2_required",
            "schema_version IS NULL OR schema_version != '2.0' OR status = 'deleted' OR "
            "(memory_kind_v2 IS NOT NULL AND content IS NOT NULL AND content != '' "
            "AND applies_when IS NOT NULL AND applies_when != '' "
            "AND review_status IS NOT NULL AND confidence IS NOT NULL)",
        )
        batch_op.create_index(
            "ix_memory_cards_owner_review_updated",
            ["owner_id", "review_status", "updated_at"],
        )
        batch_op.create_index("ix_memory_cards_owner_v2_kind", ["owner_id", "memory_kind_v2"])

    # Existing cards remain legacy and cannot silently become trusted G5
    # memories. Their projection is available only for explicit user review.
    op.execute(
        """
        UPDATE memory_cards
        SET memory_kind_v2 = CASE
                WHEN kind = 'preference' THEN 'preference'
                WHEN kind IN ('constraint', 'procedure') THEN 'rule'
                WHEN kind = 'experience' THEN 'experience'
                ELSE NULL
            END,
            content = CASE
                WHEN status = 'deleted' THEN NULL
                ELSE COALESCE(NULLIF(rule, ''), NULLIF(title, ''), '')
            END,
            applies_when = CASE
                WHEN status = 'deleted' THEN NULL
                ELSE COALESCE(NULLIF(trigger_text, ''), 'When this guidance is relevant')
            END,
            review_status = CASE
                WHEN status = 'deleted' THEN NULL
                ELSE 'legacy_unverified'
            END,
            confidence = CASE
                WHEN status = 'deleted' THEN NULL
                ELSE COALESCE(rule_confidence, scope_confidence, source_trust, 0.0)
            END,
            rule_subtype = CASE
                WHEN kind = 'constraint' THEN 'constraint'
                WHEN kind = 'procedure' THEN 'procedure'
                ELSE NULL
            END,
            schema_version = CASE WHEN status = 'deleted' THEN NULL ELSE '1.0' END
        """
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE memory_cards_fts USING fts5(
            memory_id UNINDEXED,
            owner_id UNINDEXED,
            content,
            applies_when,
            tokenize='unicode61'
        )
        """
    )
    op.execute(
        """
        INSERT INTO memory_cards_fts(memory_id, owner_id, content, applies_when)
        SELECT id, owner_id, COALESCE(content, ''), COALESCE(applies_when, '')
        FROM memory_cards
        WHERE schema_version = '2.0' AND status != 'deleted'
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_memory_cards_fts_insert
        AFTER INSERT ON memory_cards
        WHEN NEW.schema_version = '2.0' AND NEW.status != 'deleted'
        BEGIN
            INSERT INTO memory_cards_fts(memory_id, owner_id, content, applies_when)
            VALUES (NEW.id, NEW.owner_id, COALESCE(NEW.content, ''),
                    COALESCE(NEW.applies_when, ''));
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_memory_cards_fts_update
        AFTER UPDATE OF owner_id, content, applies_when, schema_version, status
        ON memory_cards
        BEGIN
            DELETE FROM memory_cards_fts WHERE memory_id = OLD.id;
            INSERT INTO memory_cards_fts(memory_id, owner_id, content, applies_when)
            SELECT NEW.id, NEW.owner_id, COALESCE(NEW.content, ''),
                   COALESCE(NEW.applies_when, '')
            WHERE NEW.schema_version = '2.0' AND NEW.status != 'deleted';
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_memory_cards_fts_delete
        AFTER DELETE ON memory_cards
        BEGIN
            DELETE FROM memory_cards_fts WHERE memory_id = OLD.id;
        END
        """
    )

    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.add_column(sa.Column("memory_kind_v2", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("content", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("applies_when", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("review_status", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("rule_subtype", sa.String(32), nullable=True))
        batch_op.drop_constraint("chk_memory_version_created_by", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_version_created_by",
            "created_by_action IN ('accept', 'edit_accept', 'edit', 'import', "
            "'merge', 'scope_resolution', 'llm_extract', 'llm_update', "
            "'llm_supersede', 'llm_coexist', 'user_edit')",
        )
        batch_op.create_check_constraint(
            "chk_memory_version_v2_kind",
            "memory_kind_v2 IS NULL OR memory_kind_v2 IN ('preference', 'rule', 'experience')",
        )
        batch_op.create_unique_constraint("uq_memory_versions_owner_id", ["owner_id", "id"])

    op.execute(
        """
        UPDATE memory_versions
        SET memory_kind_v2 = (
                SELECT memory_kind_v2 FROM memory_cards
                WHERE memory_cards.id = memory_versions.memory_id
            ),
            content = COALESCE(NULLIF(rule, ''), NULLIF(title, ''), ''),
            applies_when = COALESCE(NULLIF(trigger_text, ''),
                'When this guidance is relevant'),
            confidence = (
                SELECT confidence FROM memory_cards
                WHERE memory_cards.id = memory_versions.memory_id
            ),
            review_status = 'legacy_unverified',
            rule_subtype = (
                SELECT rule_subtype FROM memory_cards
                WHERE memory_cards.id = memory_versions.memory_id
            )
        """
    )

    op.create_table(
        "memory_event_cursors",
        sa.Column(
            "owner_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("next_seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("next_seq >= 1", name="chk_memory_event_cursor_next_seq"),
    )

    op.create_table(
        "memory_reflection_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("user_message_id", sa.String(64), nullable=False),
        sa.Column("assistant_message_id", sa.String(64), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mutation_decision", sa.String(32), nullable=True),
        sa.Column("provider_model", sa.String(128), nullable=False),
        sa.Column("prompt_hash", sa.String(71), nullable=True),
        sa.Column("schema_version", sa.String(16), nullable=False, server_default="2.0"),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("token_source", sa.String(16), nullable=True),
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
        sa.CheckConstraint("attempt >= 0", name="chk_reflection_job_attempt"),
        sa.CheckConstraint("turn_index >= 1", name="chk_reflection_job_turn_index"),
        sa.CheckConstraint("schema_version = '2.0'", name="chk_reflection_job_schema_version"),
        sa.CheckConstraint(
            "token_source IS NULL OR token_source IN ('actual', 'mock')",
            name="chk_reflection_job_token_source",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "task_id"],
            ["tasks.owner_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "task_id", "run_id"],
            ["agent_runs.owner_id", "agent_runs.task_id", "agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "user_message_id"],
            ["messages.owner_id", "messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "assistant_message_id"],
            ["messages.owner_id", "messages.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("owner_id", "id", name="uq_reflection_jobs_owner_id"),
        sa.UniqueConstraint(
            "owner_id",
            "task_id",
            "run_id",
            "turn_index",
            name="uq_reflection_job_turn",
        ),
    )
    op.create_index(
        "ix_reflection_jobs_owner_task",
        "memory_reflection_jobs",
        ["owner_id", "task_id"],
    )
    op.create_index(
        "ix_reflection_jobs_status_lease",
        "memory_reflection_jobs",
        ["status", "lease_expires_at", "created_at"],
    )

    op.create_table(
        "memory_llm_judgments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("memory_id", sa.String(64), nullable=True),
        sa.Column("judge_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("provider_model", sa.String(128), nullable=False),
        sa.Column("prompt_hash", sa.String(71), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False, server_default="2.0"),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("token_source", sa.String(16), nullable=False),
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
            "judge_type IN ('summary', 'applicability', 'effect', 'consolidation')",
            name="chk_llm_judge_type",
        ),
        sa.CheckConstraint("status IN ('completed', 'failed')", name="chk_llm_judge_status"),
        sa.CheckConstraint("token_source IN ('actual', 'mock')", name="chk_llm_judge_token_source"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_id", "task_id"],
            ["tasks.owner_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "task_id", "run_id"],
            ["agent_runs.owner_id", "agent_runs.task_id", "agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "job_id"],
            ["memory_reflection_jobs.owner_id", "memory_reflection_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "memory_id"],
            ["memory_cards.owner_id", "memory_cards.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "task_id",
            "run_id",
            "memory_id",
            "judge_type",
            name="uq_llm_judge_run_memory_type",
        ),
    )
    op.create_index(
        "ix_llm_judgments_owner_job",
        "memory_llm_judgments",
        ["owner_id", "job_id"],
    )
    op.create_index(
        "ix_llm_judgments_owner_memory",
        "memory_llm_judgments",
        ["owner_id", "memory_id", "judge_type"],
    )

    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.add_column(sa.Column("reflection_job_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("message_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("turn_index", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("consolidation_decision", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("consolidation_confidence", sa.Float(), nullable=True))
        batch_op.alter_column(
            "feedback_id", existing_type=sa.String(64), existing_nullable=False, nullable=True
        )
        batch_op.alter_column(
            "memory_job_id", existing_type=sa.String(64), existing_nullable=False, nullable=True
        )
        batch_op.drop_constraint("chk_memory_evidence_source_type", type_="check")
        batch_op.drop_constraint("chk_memory_evidence_source_field", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_evidence_source_type",
            "source_type IN ('explicit_feedback', 'explicit_correction', 'edit_diff', "
            "'accept', 'reject', 'rating', 'outcome', 'import', 'conversation_turn', "
            "'user_edit')",
        )
        batch_op.create_check_constraint(
            "chk_memory_evidence_source_field",
            "source_field IN ('explicit_text', 'edited_output', 'rating', 'accepted', "
            "'user_message')",
        )
        batch_op.create_check_constraint(
            "chk_memory_evidence_reference",
            "feedback_id IS NOT NULL OR message_id IS NOT NULL",
        )
        batch_op.create_check_constraint(
            "chk_memory_evidence_turn_index", "turn_index IS NULL OR turn_index >= 1"
        )
        batch_op.create_check_constraint(
            "chk_memory_evidence_consolidation_confidence",
            "consolidation_confidence IS NULL OR "
            "(consolidation_confidence >= 0 AND consolidation_confidence <= 1)",
        )
        batch_op.create_foreign_key(
            "fk_memory_evidence_reflection_job",
            "memory_reflection_jobs",
            ["owner_id", "reflection_job_id"],
            ["owner_id", "id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_memory_evidence_message_owner",
            "messages",
            ["owner_id", "message_id"],
            ["owner_id", "id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "ix_memory_evidence_reflection_job", ["owner_id", "reflection_job_id"]
        )
        batch_op.create_index("ix_memory_evidence_message", ["owner_id", "message_id"])

    with op.batch_alter_table("memory_relations") as batch_op:
        batch_op.add_column(sa.Column("llm_consolidation_decision", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("consolidation_confidence", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("consolidation_decided_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            "chk_memory_relation_llm_decision",
            "llm_consolidation_decision IS NULL OR llm_consolidation_decision IN "
            "('add', 'update', 'supersede', 'coexist', 'noop')",
        )
        batch_op.create_check_constraint(
            "chk_memory_relation_llm_confidence",
            "consolidation_confidence IS NULL OR "
            "(consolidation_confidence >= 0 AND consolidation_confidence <= 1)",
        )

    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    op.execute("DROP TRIGGER IF EXISTS trg_memory_cards_fts_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_memory_cards_fts_update")
    op.execute("DROP TRIGGER IF EXISTS trg_memory_cards_fts_insert")
    op.execute("DROP TABLE IF EXISTS memory_cards_fts")

    # G5-only traces/cards cannot be represented faithfully by 005.
    op.execute("DELETE FROM retrieval_traces WHERE retrieval_mode = 'llm_judge'")
    op.execute("DELETE FROM memory_cards WHERE schema_version = '2.0'")

    with op.batch_alter_table("memory_relations") as batch_op:
        batch_op.drop_constraint("chk_memory_relation_llm_confidence", type_="check")
        batch_op.drop_constraint("chk_memory_relation_llm_decision", type_="check")
        batch_op.drop_column("consolidation_decided_at")
        batch_op.drop_column("consolidation_confidence")
        batch_op.drop_column("llm_consolidation_decision")

    # Only legacy evidence can survive the 005 not-null contract.
    op.execute("DELETE FROM memory_evidence WHERE feedback_id IS NULL")
    with op.batch_alter_table("memory_evidence") as batch_op:
        batch_op.drop_index("ix_memory_evidence_message")
        batch_op.drop_index("ix_memory_evidence_reflection_job")
        batch_op.drop_constraint("fk_memory_evidence_message_owner", type_="foreignkey")
        batch_op.drop_constraint("fk_memory_evidence_reflection_job", type_="foreignkey")
        batch_op.drop_constraint("chk_memory_evidence_consolidation_confidence", type_="check")
        batch_op.drop_constraint("chk_memory_evidence_turn_index", type_="check")
        batch_op.drop_constraint("chk_memory_evidence_reference", type_="check")
        batch_op.drop_constraint("chk_memory_evidence_source_field", type_="check")
        batch_op.drop_constraint("chk_memory_evidence_source_type", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_evidence_source_type",
            "source_type IN ('explicit_feedback', 'explicit_correction', 'edit_diff', "
            "'accept', 'reject', 'rating', 'outcome', 'import')",
        )
        batch_op.create_check_constraint(
            "chk_memory_evidence_source_field",
            "source_field IN ('explicit_text', 'edited_output', 'rating', 'accepted')",
        )
        batch_op.alter_column(
            "memory_job_id", existing_type=sa.String(64), existing_nullable=True, nullable=False
        )
        batch_op.alter_column(
            "feedback_id", existing_type=sa.String(64), existing_nullable=True, nullable=False
        )
        batch_op.drop_column("consolidation_confidence")
        batch_op.drop_column("consolidation_decision")
        batch_op.drop_column("is_primary")
        batch_op.drop_column("turn_index")
        batch_op.drop_column("message_id")
        batch_op.drop_column("reflection_job_id")

    op.drop_index("ix_llm_judgments_owner_memory", table_name="memory_llm_judgments")
    op.drop_index("ix_llm_judgments_owner_job", table_name="memory_llm_judgments")
    op.drop_table("memory_llm_judgments")
    op.drop_index("ix_reflection_jobs_status_lease", table_name="memory_reflection_jobs")
    op.drop_index("ix_reflection_jobs_owner_task", table_name="memory_reflection_jobs")
    op.drop_table("memory_reflection_jobs")
    op.drop_table("memory_event_cursors")

    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.drop_constraint("uq_memory_versions_owner_id", type_="unique")
        batch_op.drop_constraint("chk_memory_version_v2_kind", type_="check")
        batch_op.drop_constraint("chk_memory_version_created_by", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_version_created_by",
            "created_by_action IN ('accept', 'edit_accept', 'edit', 'import', "
            "'merge', 'scope_resolution')",
        )
        batch_op.drop_column("rule_subtype")
        batch_op.drop_column("review_status")
        batch_op.drop_column("confidence")
        batch_op.drop_column("applies_when")
        batch_op.drop_column("content")
        batch_op.drop_column("memory_kind_v2")

    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.drop_index("ix_memory_cards_owner_v2_kind")
        batch_op.drop_index("ix_memory_cards_owner_review_updated")
        batch_op.drop_constraint("chk_memory_card_v2_required", type_="check")
        batch_op.drop_constraint("chk_memory_card_rule_subtype", type_="check")
        batch_op.drop_constraint("chk_memory_card_v2_confidence", type_="check")
        batch_op.drop_constraint("chk_memory_card_review_status", type_="check")
        batch_op.drop_constraint("chk_memory_card_v2_kind", type_="check")
        batch_op.drop_constraint("chk_memory_card_status", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_card_status",
            "status IN ('candidate', 'active', 'rejected', 'conflicted', 'paused', "
            "'superseded', 'merged', 'archived', 'deleted')",
        )
        batch_op.drop_constraint("chk_memory_card_source_type", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_card_source_type",
            "source_type IS NULL OR source_type IN ('explicit_feedback', "
            "'explicit_correction', 'edit_diff', 'accept', 'reject', 'rating', "
            "'outcome', 'import')",
        )
        batch_op.drop_column("schema_version")
        batch_op.drop_column("rule_subtype")
        batch_op.drop_column("confidence")
        batch_op.drop_column("review_status")
        batch_op.drop_column("applies_when")
        batch_op.drop_column("content")
        batch_op.drop_column("memory_kind_v2")

    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_index("ix_messages_owner_task_turn")
        batch_op.drop_constraint("uq_messages_owner_id", type_="unique")
        batch_op.drop_constraint("chk_message_turn_index", type_="check")
        batch_op.drop_column("turn_index")

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint("uq_agent_runs_owner_task_id", type_="unique")
        batch_op.drop_constraint("chk_run_extended_usage", type_="check")
        batch_op.drop_column("schema_version")
        batch_op.drop_column("prompt_hash")
        batch_op.drop_column("provider_response_id")
        batch_op.drop_column("reasoning_tokens")
        batch_op.drop_column("total_tokens")

    with op.batch_alter_table("retrieval_traces") as batch_op:
        batch_op.drop_constraint("chk_retrieval_trace_mode", type_="check")
        batch_op.create_check_constraint(
            "chk_retrieval_trace_mode",
            "retrieval_mode IN ('tfidf', 'tfidf_degraded')",
        )

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_constraint("uq_tasks_owner_id", type_="unique")
        batch_op.drop_constraint("chk_task_conversation_cursors", type_="check")
        batch_op.drop_column("next_turn_index")
        batch_op.drop_column("summary_through_turn")
        batch_op.drop_column("conversation_summary")

    op.execute("PRAGMA foreign_keys=ON")
