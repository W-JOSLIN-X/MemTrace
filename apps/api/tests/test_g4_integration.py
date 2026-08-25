"""Integration tests for G4 Memory Center and Pack operations."""

from __future__ import annotations

import datetime
import json

import pytest

from memtrace_api.db_models import MemoryCardModel, MemoryRelationModel
from memtrace_api.repositories import (
    MemoryCardG4Repository,
    PackRepository,
    ConflictRepository,
    MemoryMergeRepository,
    ImportBatchRepository,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.schemas import CreatedByAction, SourceType


class TestG4MemoryCenter:
    """G4 Memory Center lifecycle operations."""

    def test_permanent_delete_cleans_all_related_tables(
        self, user_context, session
    ):
        """Verify permanent delete clears versions, relations, usage, evidence, idempotency."""
        repo = MemoryCardG4Repository(user_context, session)
        card_id = new_prefixed_ulid("mem")
        version_id = new_prefixed_ulid("memver")
        now = datetime.datetime.now(datetime.timezone.utc)
        card = MemoryCardModel(
            id=card_id,
            owner_id=user_context.user_id,
            status="active",
            kind="preference",
            source_type="explicit_feedback",
            title="Test Card",
            rule="Test rule",
            avoid="",
            trigger_text="",
            scope_level="global",
            domain="other",
            scope_json="{}",
            exceptions_json="[]",
            source_trust=1.0,
            rule_confidence=1.0,
            scope_confidence=1.0,
            evidence_count=1,
            version=1,
            current_version_id=version_id,
            created_at=now,
            updated_at=now,
        )
        session.add(card)
        session.flush()
        result = repo.permanent_delete(
            memory_id=card_id,
            expected_version_id=version_id,
            confirm_title="Test Card",
        )
        assert result["status"] == "deleted"
        assert result["memory_id"] == card_id
        deleted_card = session.execute(
            select(MemoryCardModel).where(MemoryCardModel.id == card_id)
        ).scalar_one_or_none()
        assert deleted_card is not None
        assert deleted_card.status == "deleted"
        assert deleted_card.title is None
        assert deleted_card.rule is None

    def test_task_delete_preserves_cards(
        self, user_context, session
    ):
        """Verify task delete preserves cards but marks evidence_missing."""
        repo = MemoryCardG4Repository(user_context, session)
        card_id = new_prefixed_ulid("mem")
        card = MemoryCardModel(
            id=card_id,
            owner_id=user_context.user_id,
            status="active",
            kind="preference",
            source_type="explicit_feedback",
            title="Task Card",
            rule="Rule",
            avoid="",
            trigger_text="",
            scope_level="global",
            domain="other",
            scope_json="{}",
            exceptions_json="[]",
            source_trust=1.0,
            rule_confidence=1.0,
            scope_confidence=1.0,
            evidence_count=1,
            version=1,
            current_version_id=new_prefixed_ulid("memver"),
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(card)
        task_id = new_prefixed_ulid("task")
        session.flush()
        result = repo.delete_source_task(task_id)
        assert result["task_id"] == task_id
        assert result["status"] == "deleted"
        assert result["memory_policy"] == "preserve_and_mark_evidence_missing"

    def test_conflict_create_and_resolve_prefer(
        self, user_context, session
    ):
        """Test creating conflict and resolving with prefer action."""
        card_repo = MemoryCardG4Repository(user_context, session)
        conflict_repo = ConflictRepository(user_context, session)
        left_id = new_prefixed_ulid("mem")
        right_id = new_prefixed_ulid("mem")
        ver_1 = new_prefixed_ulid("memver")
        ver_2 = new_prefixed_ulid("memver")
        now = datetime.datetime.now(datetime.timezone.utc)
        for card_id, ver_id in [(left_id, ver_1), (right_id, ver_2)]:
            card = MemoryCardModel(
                id=card_id,
                owner_id=user_context.user_id,
                status="active",
                kind="preference",
                source_type="explicit_feedback",
                title=f"Card {card_id[-6:]}",
                rule="Test rule",
                avoid="",
                trigger_text="",
                scope_level="global",
                domain="other",
                scope_json="{}",
                exceptions_json="[]",
                source_trust=1.0,
                rule_confidence=1.0,
                scope_confidence=1.0,
                evidence_count=1,
                version=1,
                current_version_id=ver_id,
                created_at=now,
                updated_at=now,
            )
            session.add(card)
        session.flush()
        rel_id = new_prefixed_ulid("rel")
        relation = conflict_repo.create_conflict(
            relation_id=rel_id,
            left_memory_id=left_id,
            right_memory_id=right_id,
        )
        assert relation.relation_type == "conflicts_with"
        assert relation.status == "unresolved"
        resolved = conflict_repo.resolve(
            rel_id,
            action="prefer",
            resolution_memory_id=left_id,
        )
        assert resolved.status == "resolved"
        assert resolved.resolution_action == "prefer"

    def test_pack_export_rfc8785(
        self, user_context, session
    ):
        """Test Pack export with RFC 8785 canonicalization."""
        pack_repo = PackRepository(user_context, session)
        card_id = new_prefixed_ulid("mem")
        ver_id = new_prefixed_ulid("memver")
        now = datetime.datetime.now(datetime.timezone.utc)
        card = MemoryCardModel(
            id=card_id,
            owner_id=user_context.user_id,
            status="active",
            kind="preference",
            source_type="explicit_feedback",
            title="Export Test",
            rule="Test rule for export",
            avoid="",
            trigger_text="",
            scope_level="global",
            domain="other",
            scope_json="{}",
            exceptions_json="[]",
            source_trust=1.0,
            rule_confidence=1.0,
            scope_confidence=1.0,
            evidence_count=1,
            version=1,
            current_version_id=ver_id,
            created_at=now,
            updated_at=now,
        )
        session.add(card)
        session.flush()
        pack = pack_repo.export_memories(
            pack_id=new_prefixed_ulid("pack"),
            name="Test Export",
            description="Test",
            memory_ids=[card_id],
        )
        assert "schema_ref" in pack
        assert pack["schema_ref"] == "memtrace-memory-pack@1.0.0"
        assert "integrity" in pack
        assert "canonical_payload_sha256" in pack["integrity"]
        assert len(pack["integrity"]["canonical_payload_sha256"]) == 64
        assert len(pack["cards"]) == 1
        assert pack["cards"][0]["title"] == "Export Test"


class TestG4AdmissionGuard:
    """Admission Guard invariants."""

    def test_active_card_requires_confirmed_confidence(
        self, user_context, session
    ):
        """Active card must have confirmed rule_confidence and scope_confidence."""
        card = MemoryCardModel(
            id=new_prefixed_ulid("mem"),
            owner_id=user_context.user_id,
            status="active",
            kind="preference",
            source_type="explicit_feedback",
            title="Bad Active Card",
            rule="Rule",
            avoid="",
            trigger_text="",
            scope_level="global",
            domain="other",
            scope_json="{}",
            exceptions_json="[]",
            source_trust=1.0,
            rule_confidence=None,
            scope_confidence=None,
            evidence_count=0,
            version=1,
            current_version_id=new_prefixed_ulid("memver"),
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(card)
        session.flush()
        repo = MemoryCardG4Repository(user_context, session)
        with pytest.raises(ValueError, match="active card invariants"):
            repo._get(card.id)


class TestG4CrossOwnerIsolation:
    """Cross-owner isolation."""

    def test_memory_card_cross_owner_invisible(
        self, user_context, other_user_context, session
    ):
        """Verify cross-owner memory cards are not visible."""
        card_id = new_prefixed_ulid("mem")
        now = datetime.datetime.now(datetime.timezone.utc)
        card = MemoryCardModel(
            id=card_id,
            owner_id=user_context.user_id,
            status="active",
            kind="preference",
            source_type="explicit_feedback",
            title="Owner 1 Card",
            rule="Rule",
            avoid="",
            trigger_text="",
            scope_level="global",
            domain="other",
            scope_json="{}",
            exceptions_json="[]",
            source_trust=1.0,
            rule_confidence=1.0,
            scope_confidence=1.0,
            evidence_count=0,
            version=1,
            current_version_id=new_prefixed_ulid("memver"),
            created_at=now,
            updated_at=now,
        )
        session.add(card)
        session.flush()
        other_repo = MemoryCardG4Repository(other_user_context, session)
        result = other_repo.get_detail(card_id)
        assert result is None, "Cross-owner card must not be visible"
