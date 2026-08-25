"""005_g4_memory_center_pack

Revision ID: 0b5da423ff7c
Revises: 004_g3_retrieval_usage
Create Date: 2026-08-25 21:25:12.011928

G4 additions:
- Task tombstone columns (deleted_at, deleted_by, deletion_reason)
- MemoryCard G4 columns (evidence_missing, deleted_at, import_batch_id, import_source_version)
- MemoryRelation G4 columns (status, resolution_action, resolution_memory_id, resolved_at)
- MemoryVersion extended created_by_action (import, merge, scope_resolution)
- ImportBatchModel table
- Owner-scoped indexes for list/search/filter
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b5da423ff7c'
down_revision: str | None = '004_g3_retrieval_usage'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply G4 Memory Center and Pack schema changes."""

    # --- Task tombstone columns ---
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('deleted_by', sa.String(32), nullable=True))
        batch_op.add_column(sa.Column('deletion_reason', sa.String(64), nullable=True))

    # Update task status check constraint to include 'deleted'
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_constraint('chk_task_status', type_='check')
        batch_op.create_check_constraint(
            'chk_task_status',
            "status IN ('active', 'archived', 'deleted')",
        )
        batch_op.create_check_constraint(
            'chk_task_deleted_tombstone',
            "status = 'deleted' OR (deleted_at IS NULL AND deleted_by IS NULL AND deletion_reason IS NULL)",
        )

    # --- MemoryCard G4 columns ---
    with op.batch_alter_table('memory_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('evidence_missing', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('import_batch_id', sa.String(64), nullable=True))
        batch_op.add_column(sa.Column('import_source_version', sa.Integer(), nullable=True))

    # Add G4 check constraints for memory_cards
    with op.batch_alter_table('memory_cards', schema=None) as batch_op:
        batch_op.create_check_constraint(
            'chk_memory_card_g4_deleted_tombstone',
            "status = 'deleted' OR (deleted_at IS NULL AND evidence_missing = 0)",
        )
        batch_op.create_check_constraint(
            'chk_memory_card_import_source_version',
            "import_source_version IS NULL OR import_source_version >= 1",
        )

    # Create index on import_batch_id
    op.create_index(
        'ix_memory_cards_import_batch',
        'memory_cards',
        ['import_batch_id'],
    )

    # Create foreign key for import_batch_id (must be separate from batch_alter_table)
    with op.batch_alter_table('memory_cards', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_memory_cards_import_batch',
            'import_batches',
            ['import_batch_id'],
            ['id'],
            ondelete='SET NULL',
        )

    # --- MemoryRelation G4 columns ---
    with op.batch_alter_table('memory_relations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(32), nullable=False, server_default='resolved'))
        batch_op.add_column(sa.Column('resolution_action', sa.String(32), nullable=True))
        batch_op.add_column(sa.Column('resolution_memory_id', sa.String(64), nullable=True))
        batch_op.add_column(sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))

    # Drop old constraint and add new ones
    with op.batch_alter_table('memory_relations', schema=None) as batch_op:
        batch_op.drop_constraint('chk_memory_relation_type', type_='check')
        batch_op.create_check_constraint(
            'chk_memory_relation_type',
            "relation_type IN ('duplicate_of', 'conflicts_with', 'supersedes', "
            "'reinforces', 'merged_into', 'related_to')",
        )
        batch_op.create_check_constraint(
            'chk_memory_relation_status',
            "status IN ('unresolved', 'resolved')",
        )
        batch_op.create_check_constraint(
            'chk_memory_relation_resolution_action',
            "resolution_action IS NULL OR resolution_action IN "
            "('prefer', 'separate_scopes', 'merge', 'pause_both')",
        )
        batch_op.create_check_constraint(
            'chk_memory_relation_unresolved_state',
            "(status = 'resolved') OR (resolution_action IS NULL AND resolved_at IS NULL)",
        )

    # Create indexes for memory_relations
    op.create_index('ix_memory_relations_owner', 'memory_relations', ['owner_id'])

    # Drop old unique constraint and add new one
    with op.batch_alter_table('memory_relations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_memory_relation_triple', type_='unique')
        batch_op.create_unique_constraint(
            'uq_memory_relation_pair',
            ['from_memory_id', 'to_memory_id'],
        )

    # --- MemoryVersion extended created_by_action ---
    with op.batch_alter_table('memory_versions', schema=None) as batch_op:
        batch_op.drop_constraint('chk_memory_version_created_by', type_='check')
        batch_op.create_check_constraint(
            'chk_memory_version_created_by',
            "created_by_action IN ('accept', 'edit_accept', 'edit', 'import', 'merge', 'scope_resolution')",
        )

    # --- ImportBatchModel table ---
    op.create_table(
        'import_batches',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column(
            'owner_id',
            sa.String(64),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='quarantined'),
        sa.Column('canonical_payload_json', sa.Text(), nullable=True),
        sa.Column('preview_json', sa.Text(), nullable=True),
        sa.Column('preview_token_hash', sa.String(64), nullable=True, index=True),
        sa.Column('inserted_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('warning_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('quarantined', 'committed', 'expired', 'cancelled')",
            name='chk_import_batch_status',
        ),
        sa.CheckConstraint(
            'inserted_count >= 0 AND skipped_count >= 0 AND warning_count >= 0',
            name='chk_import_batch_counts',
        ),
        sa.UniqueConstraint('preview_token_hash', name='uq_import_batch_preview_token'),
    )
    op.create_index('ix_import_batches_owner', 'import_batches', ['owner_id'])
    op.create_index('ix_import_batches_expires', 'import_batches', ['expires_at'])

    # Add foreign key from memory_cards to import_batches
    with op.batch_alter_table('memory_cards', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_memory_cards_import_batch',
            'import_batches',
            ['import_batch_id'],
            ['id'],
            ondelete='SET NULL',
        )

    # --- G4 owner-scoped indexes ---
    # These are covered by existing ix_memory_cards_owner_status_scope
    # No additional indexes needed at this time


def downgrade() -> None:
    """Downgrade G4 changes, restoring G3 schema."""

    # Drop import_batches table
    op.drop_table('import_batches')

    # Remove memory_cards foreign key and columns
    with op.batch_alter_table('memory_cards', schema=None) as batch_op:
        batch_op.drop_constraint('fk_memory_cards_import_batch', type_='foreignkey')
        batch_op.drop_constraint('chk_memory_card_g4_deleted_tombstone', type_='check')
        batch_op.drop_constraint('chk_memory_card_import_source_version', type_='check')
        batch_op.drop_index('ix_memory_cards_import_batch')
        batch_op.drop_column('import_source_version')
        batch_op.drop_column('import_batch_id')
        batch_op.drop_column('deleted_at')
        batch_op.drop_column('evidence_missing')

    # Restore memory_relations to G3 state
    with op.batch_alter_table('memory_relations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_memory_relation_pair', type_='unique')
        batch_op.drop_constraint('chk_memory_relation_unresolved_state', type_='check')
        batch_op.drop_constraint('chk_memory_relation_resolution_action', type_='check')
        batch_op.drop_constraint('chk_memory_relation_status', type_='check')
        batch_op.drop_constraint('chk_memory_relation_type', type_='check')
        batch_op.drop_column('resolved_at')
        batch_op.drop_column('resolution_memory_id')
        batch_op.drop_column('resolution_action')
        batch_op.drop_column('status')
        # Recreate original type check
        batch_op.create_check_constraint(
            'chk_memory_relation_type',
            "relation_type IN ('duplicate_of', 'conflicts_with', 'supersedes', 'related_to')",
        )
        batch_op.create_unique_constraint(
            'uq_memory_relation_triple',
            ['from_memory_id', 'to_memory_id', 'relation_type'],
        )

    op.drop_index('ix_memory_relations_owner', 'memory_relations')

    # Restore memory_versions to G3 state
    with op.batch_alter_table('memory_versions', schema=None) as batch_op:
        batch_op.drop_constraint('chk_memory_version_created_by', type_='check')
        batch_op.create_check_constraint(
            'chk_memory_version_created_by',
            "created_by_action IN ('accept', 'edit_accept', 'edit')",
        )

    # Restore tasks to G3 state
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_constraint('chk_task_deleted_tombstone', type_='check')
        batch_op.drop_constraint('chk_task_status', type_='check')
        batch_op.create_check_constraint(
            'chk_task_status',
            "status IN ('active', 'archived')",
        )
        batch_op.drop_column('deletion_reason')
        batch_op.drop_column('deleted_by')
        batch_op.drop_column('deleted_at')
