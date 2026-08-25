"""G4 Memory Center, conflict resolution, Pack import and safe tombstones.

Revision ID: 005_g4_memory_center_pack
Revises: 004_g3_retrieval_usage
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_g4_memory_center_pack"
down_revision: str | None = "004_g3_retrieval_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The batch operations below rebuild SQLite parent tables. Keep foreign keys
    # disabled for the migration connection so dropping the temporary source
    # table cannot cascade-delete otherwise unrelated G1-G3 child rows.
    op.execute("PRAGMA foreign_keys=OFF")

    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("pack_name", sa.String(80), nullable=True),
        sa.Column("format_version", sa.String(16), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="quarantined"),
        sa.Column("canonical_payload_json", sa.Text(), nullable=True),
        sa.Column("preview_json", sa.Text(), nullable=True),
        sa.Column("preview_token_hash", sa.String(64), nullable=True),
        sa.Column("inserted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('quarantined', 'committed', 'expired', 'cancelled')",
            name="chk_import_batch_status",
        ),
        sa.CheckConstraint(
            "inserted_count >= 0 AND skipped_count >= 0 AND warning_count >= 0",
            name="chk_import_batch_counts",
        ),
        sa.CheckConstraint(
            "(status = 'committed' AND committed_at IS NOT NULL) OR "
            "(status != 'committed' AND committed_at IS NULL)",
            name="chk_import_batch_committed",
        ),
        sa.UniqueConstraint("preview_token_hash", name="uq_import_batch_preview_token"),
    )
    op.create_index("ix_import_batches_owner", "import_batches", ["owner_id"])
    op.create_index("ix_import_batches_expires", "import_batches", ["expires_at"])
    op.create_index(
        "ix_import_batches_preview_token_hash", "import_batches", ["preview_token_hash"]
    )

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deleted_by", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("deletion_reason", sa.String(64), nullable=True))
        batch_op.drop_constraint("chk_task_status", type_="check")
        batch_op.create_check_constraint(
            "chk_task_status", "status IN ('active', 'archived', 'deleted')"
        )
        batch_op.create_check_constraint(
            "chk_task_deleted_tombstone",
            "(status = 'deleted' AND deleted_at IS NOT NULL AND task_text = '') OR "
            "(status != 'deleted' AND deleted_at IS NULL AND deleted_by IS NULL "
            "AND deletion_reason IS NULL)",
        )

    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.add_column(
            sa.Column("evidence_missing", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("import_batch_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("import_source_version", sa.Integer(), nullable=True))
        for column_name, column_type in (
            ("kind", sa.String(32)),
            ("source_type", sa.String(32)),
            ("title", sa.Text()),
            ("rule", sa.Text()),
            ("avoid", sa.Text()),
            ("trigger_text", sa.Text()),
            ("scope_level", sa.String(32)),
            ("domain", sa.String(32)),
            ("scope_json", sa.Text()),
            ("exceptions_json", sa.Text()),
            ("source_trust", sa.Float()),
        ):
            batch_op.alter_column(
                column_name,
                existing_type=column_type,
                nullable=True,
            )
        batch_op.create_check_constraint(
            "chk_memory_card_g4_deleted_tombstone",
            "(status = 'deleted' AND deleted_at IS NOT NULL) OR "
            "(status != 'deleted' AND deleted_at IS NULL)",
        )
        batch_op.create_check_constraint(
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
        batch_op.create_check_constraint(
            "chk_memory_card_import_source_version",
            "import_source_version IS NULL OR import_source_version >= 1",
        )
        batch_op.create_unique_constraint("uq_memory_cards_owner_id", ["owner_id", "id"])
        batch_op.create_foreign_key(
            "fk_memory_cards_import_batch",
            "import_batches",
            ["import_batch_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_memory_cards_import_batch", ["import_batch_id"])

    with op.batch_alter_table("memory_relations") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(32), nullable=False, server_default="resolved")
        )
        batch_op.add_column(sa.Column("resolution_action", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("resolution_memory_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.drop_constraint("chk_memory_relation_type", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_relation_type",
            "relation_type IN ('duplicate_of', 'conflicts_with', 'supersedes', "
            "'reinforces', 'merged_into', 'related_to')",
        )
        batch_op.create_check_constraint(
            "chk_memory_relation_status", "status IN ('unresolved', 'resolved')"
        )
        batch_op.create_check_constraint(
            "chk_memory_relation_resolution_action",
            "resolution_action IS NULL OR resolution_action IN "
            "('prefer', 'separate_scopes', 'merge', 'pause_both')",
        )
        batch_op.create_check_constraint(
            "chk_memory_relation_resolution_state",
            "(status = 'unresolved' AND relation_type = 'conflicts_with' "
            "AND resolution_action IS NULL AND resolution_memory_id IS NULL "
            "AND resolved_at IS NULL) OR "
            "(status = 'resolved' AND (relation_type != 'conflicts_with' OR "
            "(resolution_action IS NOT NULL AND resolved_at IS NOT NULL)))",
        )
        batch_op.create_foreign_key(
            "fk_memory_relations_from_owner",
            "memory_cards",
            ["owner_id", "from_memory_id"],
            ["owner_id", "id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_memory_relations_to_owner",
            "memory_cards",
            ["owner_id", "to_memory_id"],
            ["owner_id", "id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_memory_relations_resolution_owner",
            "memory_cards",
            ["owner_id", "resolution_memory_id"],
            ["owner_id", "id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_memory_relations_owner_status", ["owner_id", "status"])

    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.drop_constraint("chk_memory_version_created_by", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_version_created_by",
            "created_by_action IN ('accept', 'edit_accept', 'edit', 'import', "
            "'merge', 'scope_resolution')",
        )

    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")

    # Deleted rows contain no recoverable content and cannot satisfy the G3
    # non-null/state checks. Removing only tombstones is the safe downgrade.
    op.execute("DELETE FROM memory_cards WHERE status = 'deleted'")
    op.execute("DELETE FROM tasks WHERE status = 'deleted'")

    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.drop_constraint("chk_memory_version_created_by", type_="check")
        batch_op.create_check_constraint(
            "chk_memory_version_created_by",
            "created_by_action IN ('accept', 'edit_accept', 'edit')",
        )

    with op.batch_alter_table("memory_relations") as batch_op:
        batch_op.drop_index("ix_memory_relations_owner_status")
        batch_op.drop_constraint("fk_memory_relations_resolution_owner", type_="foreignkey")
        batch_op.drop_constraint("fk_memory_relations_to_owner", type_="foreignkey")
        batch_op.drop_constraint("fk_memory_relations_from_owner", type_="foreignkey")
        batch_op.drop_constraint("chk_memory_relation_resolution_state", type_="check")
        batch_op.drop_constraint("chk_memory_relation_resolution_action", type_="check")
        batch_op.drop_constraint("chk_memory_relation_status", type_="check")
        batch_op.drop_constraint("chk_memory_relation_type", type_="check")
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("resolution_memory_id")
        batch_op.drop_column("resolution_action")
        batch_op.drop_column("status")
        batch_op.create_check_constraint(
            "chk_memory_relation_type",
            "relation_type IN ('duplicate_of', 'conflicts_with', 'supersedes', 'related_to')",
        )

    # Drop the MemoryCard -> ImportBatch reference and index before its target
    # table, then restore the exact G3 non-null shape.
    with op.batch_alter_table("memory_cards") as batch_op:
        batch_op.drop_index("ix_memory_cards_import_batch")
        batch_op.drop_constraint("fk_memory_cards_import_batch", type_="foreignkey")
        batch_op.drop_constraint("uq_memory_cards_owner_id", type_="unique")
        batch_op.drop_constraint("chk_memory_card_import_source_version", type_="check")
        batch_op.drop_constraint("chk_memory_card_g4_content_state", type_="check")
        batch_op.drop_constraint("chk_memory_card_g4_deleted_tombstone", type_="check")
        batch_op.drop_column("import_source_version")
        batch_op.drop_column("import_batch_id")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("evidence_missing")
        for column_name, column_type in (
            ("kind", sa.String(32)),
            ("source_type", sa.String(32)),
            ("title", sa.Text()),
            ("rule", sa.Text()),
            ("avoid", sa.Text()),
            ("trigger_text", sa.Text()),
            ("scope_level", sa.String(32)),
            ("domain", sa.String(32)),
            ("scope_json", sa.Text()),
            ("exceptions_json", sa.Text()),
            ("source_trust", sa.Float()),
        ):
            batch_op.alter_column(
                column_name,
                existing_type=column_type,
                nullable=False,
            )

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_constraint("chk_task_deleted_tombstone", type_="check")
        batch_op.drop_constraint("chk_task_status", type_="check")
        batch_op.create_check_constraint("chk_task_status", "status IN ('active', 'archived')")
        batch_op.drop_column("deletion_reason")
        batch_op.drop_column("deleted_by")
        batch_op.drop_column("deleted_at")

    op.drop_index("ix_import_batches_preview_token_hash", table_name="import_batches")
    op.drop_index("ix_import_batches_expires", table_name="import_batches")
    op.drop_index("ix_import_batches_owner", table_name="import_batches")
    op.drop_table("import_batches")
    op.execute("PRAGMA foreign_keys=ON")
