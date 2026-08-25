"""Apply remaining db_models.py G4 changes."""
from __future__ import annotations

path = "apps/api/src/memtrace_api/db_models.py"
with open(path, "r") as f:
    content = f.read()

# Step 1: MemoryRelationModel - add G4 columns
old1 = (
    "    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)\n"
    "    created_at: Mapped[datetime] = mapped_column("
)
new1 = (
    "    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)\n"
    "    status: Mapped[str] = mapped_column(String(32), nullable=False, default=\"resolved\")\n"
    "    resolution_action: Mapped[str | None] = mapped_column(String(32), nullable=True)\n"
    "    resolution_memory_id: Mapped[str | None] = mapped_column(String(64), nullable=True)\n"
    "    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)\n"
    "    created_at: Mapped[datetime] = mapped_column("
)
assert old1 in content, "Step 1: MemoryRelationModel relation_type block not found"
content = content.replace(old1, new1, 1)
print("Step 1: MemoryRelationModel columns added")

# Step 2: MemoryRelationModel __table_args__
old2 = (
    '        CheckConstraint(\n'
    '            "relation_type IN (\'duplicate_of\', \'conflicts_with\', \'supersedes\', \'related_to\')",\n'
    '            name="chk_memory_relation_type",\n'
    "        ),\n"
    '        CheckConstraint("from_memory_id != to_memory_id", name="chk_memory_relation_self"),\n'
    '        UniqueConstraint(\n'
    '            "from_memory_id", "to_memory_id", "relation_type", name="uq_memory_relation_triple"\n'
    "        ),\n"
    '        Index("ix_memory_relations_from", "from_memory_id"),\n'
    '        Index("ix_memory_relations_to", "to_memory_id"),\n'
    "    )\n"
)
new2 = (
    '        CheckConstraint(\n'
    '            "relation_type IN (\'duplicate_of\', \'conflicts_with\', \'supersedes\', '
    '\'related_to\', \'reinforces\', \'merged_into\')",\n'
    '            name="chk_memory_relation_type",\n'
    "        ),\n"
    '        CheckConstraint("from_memory_id != to_memory_id", name="chk_memory_relation_self"),\n'
    '        CheckConstraint(\n'
    '            "status IN (\'unresolved\', \'resolved\')",\n'
    '            name="chk_memory_relation_status",\n'
    "        ),\n"
    '        CheckConstraint(\n'
    '            "resolution_action IS NULL OR resolution_action IN (\'prefer\', \'separate_scopes\', \'merge\', \'pause_both\')",\n'
    '            name="chk_memory_relation_resolution_action",\n'
    "        ),\n"
    '        UniqueConstraint(\n'
    '            "from_memory_id", "to_memory_id", "relation_type",\n'
    '            name="uq_memory_relation_triple",\n'
    "        ),\n"
    '        Index("ix_memory_relations_from", "from_memory_id"),\n'
    '        Index("ix_memory_relations_to", "to_memory_id"),\n'
    '        Index("ix_memory_relations_owner_status", "owner_id", "status"),\n'
    '        Index("ix_memory_relations_resolution_action", "resolution_action"),\n'
    "    )\n"
)
assert old2 in content, "Step 2: MemoryRelationModel __table_args__ not found"
content = content.replace(old2, new2, 1)
print("Step 2: MemoryRelationModel constraints extended")

# Step 3: MemoryVersionModel - extend created_by_action
old3 = '            "created_by_action IN (\'accept\', \'edit_accept\', \'edit\')",\n'
new3 = (
    '            "created_by_action IN (\'accept\', \'edit_accept\', \'edit\', '
    '\'import\', \'merge\', \'scope_resolution\')",\n'
)
assert old3 in content, f"Step 3: MemoryVersionModel created_by_action not found"
content = content.replace(old3, new3, 1)
print("Step 3: MemoryVersionModel created_by_action extended")

# Step 4: Append ImportBatchModel
batch = '''

# ===========================================================================
# Day 5 G4: ImportBatchModel
# ===========================================================================


class ImportBatchModel(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inserted_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
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
            "committed_at IS NULL OR status = 'committed'",
            name="chk_import_batch_committed_status",
        ),
        Index("ix_import_batches_owner", "owner_id"),
        Index("ix_import_batches_owner_status", "owner_id", "status"),
    )
'''
assert "class ImportBatchModel" not in content, "ImportBatchModel already exists"
content = content.rstrip() + "\n" + batch
print("Step 4: ImportBatchModel appended")

with open(path, "w") as f:
    f.write(content)
print("All db_models.py G4 changes written successfully")
