"""Block A: DB model existence tests for G4 tables."""

from __future__ import annotations

import pytest

from memtrace_api.db_models import (
    ImportBatchModel,
    MemoryCardModel,
    MemoryRelationModel,
    MemoryVersionModel,
    TaskModel,
    UserModel,
)


class TestG4DBModels:
    def test_import_batch_model_exists(self) -> None:
        assert ImportBatchModel.__tablename__ == "import_batches"

    def test_import_batch_has_required_columns(self) -> None:
        cols = {c.name for c in ImportBatchModel.__table__.columns}
        required = {
            "id", "owner_id", "file_hash", "status",
            "canonical_payload_json", "preview_json", "preview_token_hash",
            "inserted_count", "skipped_count", "warning_count",
            "error_message", "expires_at", "created_at", "updated_at",
        }
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_memory_card_has_g4_columns(self) -> None:
        cols = {c.name for c in MemoryCardModel.__table__.columns}
        required = {"evidence_missing", "deleted_at", "import_batch_id", "import_source_version"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_memory_version_has_g4_created_by_action(self) -> None:
        # The check constraint must include G4 values
        for cc in MemoryVersionModel.__table__.constraints:
            if getattr(cc, "name", None) == "chk_memory_version_created_by":
                sql = cc.sqltext.text
                assert "import" in sql
                assert "merge" in sql
                assert "scope_resolution" in sql
                return
        pytest.fail("chk_memory_version_created_by constraint not found")

    def test_memory_relation_has_g4_columns(self) -> None:
        cols = {c.name for c in MemoryRelationModel.__table__.columns}
        required = {"status", "resolution_action", "resolution_memory_id", "resolved_at"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_memory_relation_has_g4_types(self) -> None:
        for cc in MemoryRelationModel.__table__.constraints:
            name = getattr(cc, "name", None)
            if name == "chk_memory_relation_type":
                sql = cc.sqltext.text
                assert "reinforces" in sql
                assert "merged_into" in sql
            elif name == "chk_memory_relation_status":
                sql = cc.sqltext.text
                assert "unresolved" in sql
                assert "resolved" in sql
            elif name == "chk_memory_relation_resolution_action":
                sql = cc.sqltext.text
                assert "separate_scopes" in sql
                assert "pause_both" in sql

    def test_task_model_has_tombstone_columns(self) -> None:
        cols = {c.name for c in TaskModel.__table__.columns}
        required = {"deleted_at", "deleted_by", "deletion_reason"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_task_model_deleted_tombstone_constraint(self) -> None:
        for cc in TaskModel.__table__.constraints:
            if getattr(cc, "name", None) == "chk_task_deleted_tombstone":
                return
        pytest.fail("chk_task_deleted_tombstone constraint not found")
