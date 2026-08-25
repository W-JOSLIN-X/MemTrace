"""Database-backed integration tests for G4 owner isolation and invariants."""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from memtrace_api.db_models import MemoryCardModel, MemoryVersionModel, TaskModel
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.repositories import ConflictRepository, MemoryCardG4Repository, PackRepository


def _scope_json() -> str:
    return json.dumps(
        {
            "level": "global",
            "domain": "other",
            "task_type": "any",
            "artifact_type": "any",
            "audience": "any",
            "project_key": None,
            "language": "any",
            "framework": None,
            "concepts": [],
        },
        separators=(",", ":"),
    )


def _active_card(session, owner_id: str, label: str) -> MemoryCardModel:
    now = datetime.datetime.now(datetime.UTC)
    card = MemoryCardModel(
        id=new_prefixed_ulid("mem"),
        owner_id=owner_id,
        status="candidate",
        kind="preference",
        source_type="explicit_feedback",
        title=f"{label} memory card",
        rule=f"Always apply the verified {label} rule in matching future tasks.",
        avoid="",
        trigger_text=f"matching {label} task",
        scope_level="global",
        domain="other",
        task_type="any",
        artifact_type="any",
        audience="any",
        scope_json=_scope_json(),
        exceptions_json="[]",
        source_trust=1.0,
        rule_confidence=None,
        scope_confidence=None,
        evidence_count=1,
        version=0,
        created_at=now,
        updated_at=now,
    )
    session.add(card)
    session.flush()
    version = MemoryVersionModel(
        id=new_prefixed_ulid("memver"),
        owner_id=owner_id,
        memory_id=card.id,
        version=1,
        title=card.title,
        rule=card.rule,
        avoid=card.avoid,
        trigger_text=card.trigger_text,
        scope_json=card.scope_json,
        exceptions_json=card.exceptions_json,
        created_by_action="accept",
        created_at=now,
    )
    session.add(version)
    session.flush()
    card.status = "active"
    card.version = 1
    card.current_version_id = version.id
    card.rule_confidence = 1.0
    card.scope_confidence = 1.0
    card.valid_from = now
    session.flush()
    return card


def test_permanent_delete_keeps_only_safe_tombstone(user_context, session) -> None:
    card = _active_card(session, user_context.user_id, "delete")
    version_id = card.current_version_id
    result = MemoryCardG4Repository(user_context, session).permanent_delete(
        memory_id=card.id,
        expected_version_id=version_id,
        confirm_title=card.title,
    )
    assert result["status"] == "deleted"
    deleted = session.execute(
        select(MemoryCardModel).where(MemoryCardModel.id == card.id)
    ).scalar_one()
    assert deleted.status == "deleted"
    assert deleted.title is None and deleted.rule is None and deleted.scope_json is None
    assert deleted.current_version_id is None
    assert session.get(MemoryVersionModel, version_id) is None


def test_task_delete_creates_body_free_tombstone(user_context, session) -> None:
    now = datetime.datetime.now(datetime.UTC)
    task = TaskModel(
        id=new_prefixed_ulid("task"),
        owner_id=user_context.user_id,
        scenario="other",
        task_text="synthetic task body that must be removed",
        effective_memory_mode="on",
        status="active",
        next_event_seq=1,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    session.flush()
    result = MemoryCardG4Repository(user_context, session).delete_source_task(task.id)
    assert result["task_id"] == task.id
    assert result["affected_card_count"] == 0
    session.refresh(task)
    assert task.task_text == "" and task.deleted_at is not None


def test_conflict_repository_enforces_owner_and_resolves(user_context, session) -> None:
    left = _active_card(session, user_context.user_id, "left")
    right = _active_card(session, user_context.user_id, "right")
    repository = ConflictRepository(user_context, session)
    relation = repository.create_conflict(
        relation_id=new_prefixed_ulid("rel"),
        left_memory_id=left.id,
        right_memory_id=right.id,
    )
    assert relation.status == "unresolved"
    resolved = repository.resolve(
        relation.id,
        action="prefer",
        resolution_memory_id=left.id,
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_action == "prefer"


def test_pack_export_is_anonymous_canonical_and_uses_external_ids(user_context, session) -> None:
    card = _active_card(session, user_context.user_id, "export")
    repository = PackRepository(user_context, session)
    pack = repository.export_memories(
        pack_id=new_prefixed_ulid("pack"),
        name="Synthetic export",
        description="Pack contract check",
        memory_ids=[card.id],
    )
    encoded = repository.canonical_bytes(pack)
    assert json.loads(encoded) == pack
    assert pack["cards"][0]["external_id"] == "card_001"
    assert card.id not in encoded.decode("utf-8")
    assert len(pack["integrity"]["canonical_payload_sha256"]) == 64


def test_database_rejects_active_card_without_confirmed_confidence(user_context, session) -> None:
    now = datetime.datetime.now(datetime.UTC)
    session.add(
        MemoryCardModel(
            id=new_prefixed_ulid("mem"),
            owner_id=user_context.user_id,
            status="active",
            kind="preference",
            source_type="explicit_feedback",
            title="Invalid active card",
            rule="This active rule lacks the required confirmed confidence values.",
            avoid="",
            trigger_text="invalid active test",
            scope_level="global",
            domain="other",
            scope_json=_scope_json(),
            exceptions_json="[]",
            source_trust=1.0,
            rule_confidence=None,
            scope_confidence=None,
            evidence_count=0,
            version=1,
            current_version_id=new_prefixed_ulid("memver"),
            created_at=now,
            updated_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_memory_card_cross_owner_is_invisible(user_context, other_user_context, session) -> None:
    card = _active_card(session, user_context.user_id, "private")
    assert MemoryCardG4Repository(other_user_context, session).get_detail(card.id) is None
