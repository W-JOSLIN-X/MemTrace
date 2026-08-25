"""Owner-side public API tests for the frozen Day 5 G4 contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import rfc8785
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import make_test_client
from memtrace_api.db_models import IdempotencyKeyModel, MemoryCardModel, MemoryVersionModel
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.repositories import UserRepository


def _scope(*, domain: str = "other", project_key: str | None = None) -> dict[str, object]:
    return {
        "level": "global",
        "domain": domain,
        "task_type": "any",
        "artifact_type": "any",
        "audience": "any",
        "project_key": project_key,
        "language": "any",
        "framework": None,
        "concepts": [],
    }


def _seed_active(client: TestClient, label: str, *, alias: str = "blank_demo") -> dict[str, str]:
    factory = client.app.state.db_session_factory
    with factory() as session:
        owner = UserRepository(session).get_by_alias(alias)
        assert owner is not None
        now = datetime.now(UTC)
        memory_id = new_prefixed_ulid("mem")
        card = MemoryCardModel(
            id=memory_id,
            owner_id=owner.id,
            status="candidate",
            kind="preference",
            source_type="explicit_feedback",
            title=f"{label} memory",
            rule=f"Always follow the synthetic {label} procedure for matching verification tasks.",
            avoid="",
            trigger_text=f"synthetic {label} verification",
            scope_level="global",
            domain="other",
            task_type="any",
            artifact_type="any",
            audience="any",
            scope_json=json.dumps(_scope(), separators=(",", ":")),
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
        version_id = new_prefixed_ulid("memver")
        session.add(
            MemoryVersionModel(
                id=version_id,
                owner_id=owner.id,
                memory_id=memory_id,
                version=1,
                title=card.title,
                rule=card.rule,
                avoid="",
                trigger_text=card.trigger_text,
                scope_json=card.scope_json,
                exceptions_json="[]",
                created_by_action="accept",
                created_at=now,
            )
        )
        session.flush()
        card.status = "active"
        card.version = 1
        card.current_version_id = version_id
        card.rule_confidence = 1.0
        card.scope_confidence = 1.0
        card.valid_from = now
        session.commit()
    return {"memory_id": memory_id, "version_id": version_id, "title": card.title}


def _key(value: str) -> dict[str, str]:
    return {"Idempotency-Key": f"day5-owner-{value}-0001"}


def test_edit_diff_archive_restore_resume_pause_and_stale_version(tmp_path) -> None:
    client = make_test_client(tmp_path)
    try:
        seeded = _seed_active(client, "lifecycle")
        memory_id = seeded["memory_id"]
        edited = client.patch(
            f"/api/v1/memories/{memory_id}",
            headers=_key("edit"),
            json={
                "expected_current_version_id": seeded["version_id"],
                "patch": {
                    "rule": (
                        "Always follow the revised synthetic lifecycle procedure and verify it."
                    )
                },
            },
        )
        assert edited.status_code == 200, edited.text
        version_2 = edited.json()["card"]["current_version_id"]
        assert version_2 != seeded["version_id"]

        diff = client.get(
            f"/api/v1/memories/{memory_id}/version-diff",
            params={"from_version_id": seeded["version_id"], "to_version_id": version_2},
        )
        assert diff.status_code == 200, diff.text
        assert diff.json()["changed_fields"] == ["rule"]

        stale = client.patch(
            f"/api/v1/memories/{memory_id}",
            headers=_key("stale"),
            json={
                "expected_current_version_id": seeded["version_id"],
                "patch": {"avoid": "Do not use the stale version while editing this memory."},
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "MEMORY_VERSION_CONFLICT"

        for action, expected_status in (
            ("archive", "archived"),
            ("restore", "paused"),
            ("resume", "active"),
            ("pause", "paused"),
        ):
            response = client.post(
                f"/api/v1/memories/{memory_id}/{action}",
                headers=_key(action),
                json={"expected_current_version_id": version_2},
            )
            assert response.status_code == 200, response.text
            assert response.json()["card"]["status"] == expected_status
    finally:
        client.close()


def test_conflict_pause_both_is_atomic_and_owner_scoped(tmp_path) -> None:
    client = make_test_client(tmp_path)
    try:
        first = _seed_active(client, "conflict alpha")
        second = _seed_active(client, "conflict beta")
        versions = {
            first["memory_id"]: first["version_id"],
            second["memory_id"]: second["version_id"],
        }
        detected = client.post(
            "/api/v1/memory-conflicts",
            headers=_key("conflict-detect"),
            json={
                "left_memory_id": first["memory_id"],
                "left_expected_current_version_id": first["version_id"],
                "right_memory_id": second["memory_id"],
                "right_expected_current_version_id": second["version_id"],
            },
        )
        assert detected.status_code == 200, detected.text
        body = detected.json()
        relation_id = body["relation_id"]
        resolved = client.post(
            f"/api/v1/memory-conflicts/{relation_id}/resolve",
            headers=_key("conflict-pause"),
            json={
                "expected_relation_status": "unresolved",
                "left_expected_current_version_id": versions[body["left_memory_id"]],
                "right_expected_current_version_id": versions[body["right_memory_id"]],
                "action": "pause_both",
            },
        )
        assert resolved.status_code == 200, resolved.text
        detail = client.get(f"/api/v1/memory-conflicts/{relation_id}")
        assert detail.status_code == 200
        assert detail.json()["relation"]["status"] == "resolved"
        assert {detail.json()["left"]["status"], detail.json()["right"]["status"]} == {"paused"}

        assert (
            client.post("/api/v1/session/demo", json={"demo_alias": "seeded_demo"}).status_code
            == 200
        )
        hidden = client.get(f"/api/v1/memory-conflicts/{relation_id}")
        assert hidden.status_code == 404
    finally:
        client.close()


@pytest.mark.parametrize("action", ["prefer", "separate_scopes", "merge"])
def test_remaining_conflict_resolutions_follow_frozen_state_machine(tmp_path, action) -> None:
    case_path = tmp_path / action
    case_path.mkdir()
    client = make_test_client(case_path)
    try:
        first = _seed_active(client, f"{action} alpha")
        second = _seed_active(client, f"{action} beta")
        versions = {
            first["memory_id"]: first["version_id"],
            second["memory_id"]: second["version_id"],
        }
        detected = client.post(
            "/api/v1/memory-conflicts",
            headers=_key(f"{action}-detect"),
            json={
                "left_memory_id": first["memory_id"],
                "left_expected_current_version_id": first["version_id"],
                "right_memory_id": second["memory_id"],
                "right_expected_current_version_id": second["version_id"],
            },
        )
        assert detected.status_code == 200, detected.text
        detected_body = detected.json()
        resolve_body = {
            "expected_relation_status": "unresolved",
            "left_expected_current_version_id": versions[detected_body["left_memory_id"]],
            "right_expected_current_version_id": versions[detected_body["right_memory_id"]],
            "action": action,
        }
        if action == "prefer":
            resolve_body["preferred_memory_id"] = detected_body["left_memory_id"]
        elif action == "separate_scopes":
            resolve_body["left_scope"] = _scope(domain="programming_learning")
            resolve_body["right_scope"] = _scope(domain="general_text")
        else:
            resolve_body["merged_card"] = {
                "kind": "preference",
                "title": "Manually merged memory",
                "rule": "Use the manually confirmed merged rule for this synthetic test only.",
                "avoid": "",
                "trigger_text": "manual merge verification",
                "scope": _scope(),
                "exceptions": [],
            }
        resolved = client.post(
            f"/api/v1/memory-conflicts/{detected_body['relation_id']}/resolve",
            headers=_key(f"{action}-resolve"),
            json=resolve_body,
        )
        assert resolved.status_code == 200, resolved.text
        detail = client.get(f"/api/v1/memory-conflicts/{detected_body['relation_id']}").json()
        if action == "prefer":
            assert {detail["left"]["status"], detail["right"]["status"]} == {
                "active",
                "superseded",
            }
        elif action == "separate_scopes":
            assert detail["left"]["status"] == detail["right"]["status"] == "active"
            assert detail["left"]["current_version_id"] != versions[detail["left"]["memory_id"]]
            assert detail["right"]["current_version_id"] != versions[detail["right"]["memory_id"]]
        else:
            assert detail["left"]["status"] == detail["right"]["status"] == "merged"
            merged_id = detail["relation"]["resolution_memory_id"]
            merged = client.get(f"/api/v1/memories/{merged_id}")
            assert merged.status_code == 200
            assert merged.json()["card"]["status"] == "active"
            assert merged.json()["card"]["source_type"] == "accept"
    finally:
        client.close()


def test_independent_manual_merge_creates_new_card_and_relations(tmp_path) -> None:
    client = make_test_client(tmp_path)
    try:
        left = _seed_active(client, "manual alpha")
        right = _seed_active(client, "manual beta")
        response = client.post(
            "/api/v1/memories/merge",
            headers=_key("manual-merge"),
            json={
                "left_memory_id": left["memory_id"],
                "left_expected_current_version_id": left["version_id"],
                "right_memory_id": right["memory_id"],
                "right_expected_current_version_id": right["version_id"],
                "merged_card": {
                    "kind": "preference",
                    "title": "Owner written merge",
                    "rule": (
                        "Use this owner-written merged rule for the explicit synthetic context."
                    ),
                    "avoid": "",
                    "trigger_text": "owner merge verification",
                    "scope": _scope(),
                    "exceptions": [],
                },
            },
        )
        assert response.status_code == 200, response.text
        merged_id = response.json()["merged_memory_id"]
        merged = client.get(f"/api/v1/memories/{merged_id}")
        assert merged.status_code == 200
        assert merged.json()["card"]["source_type"] == "accept"
        assert merged.json()["versions"][0]["created_by_action"] == "merge"
        for source in (left, right):
            source_detail = client.get(f"/api/v1/memories/{source['memory_id']}")
            assert source_detail.json()["card"]["status"] == "merged"
    finally:
        client.close()


def test_pack_round_trip_replay_token_privacy_and_cross_owner_batch(tmp_path) -> None:
    client = make_test_client(tmp_path)
    try:
        exported_card = _seed_active(client, "cerulean armadillo")
        exported = client.post(
            "/api/v1/memory-packs/export",
            json={"memory_ids": [exported_card["memory_id"]], "name": "Synthetic Pack"},
        )
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-disposition"].endswith('.mempack.json"')
        pack = exported.json()
        assert exported.content == rfc8785.dumps(pack)
        assert pack["cards"][0]["external_id"] == "card_001"
        assert exported_card["memory_id"].encode() not in exported.content

        assert (
            client.post("/api/v1/session/demo", json={"demo_alias": "seeded_demo"}).status_code
            == 200
        )
        preview_headers = _key("pack-preview")
        preview = client.post(
            "/api/v1/memory-packs/import/preview",
            headers=preview_headers,
            content=exported.content,
        )
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["legal_new_count"] == 1
        assert len(preview_body["preview_token"]) == 43
        replay = client.post(
            "/api/v1/memory-packs/import/preview",
            headers=preview_headers,
            content=exported.content,
        )
        assert replay.status_code == 200
        assert replay.json()["batch_id"] == preview_body["batch_id"]
        assert replay.json()["preview_token"] == preview_body["preview_token"]

        assert (
            client.post("/api/v1/session/demo", json={"demo_alias": "blank_demo"}).status_code
            == 200
        )
        assert (
            client.get(f"/api/v1/memory-packs/import/{preview_body['batch_id']}").status_code == 404
        )
        assert (
            client.post("/api/v1/session/demo", json={"demo_alias": "seeded_demo"}).status_code
            == 200
        )

        commit_payload = {
            "batch_id": preview_body["batch_id"],
            "preview_token": preview_body["preview_token"],
            "mode": "import_all_paused",
        }
        committed = client.post(
            "/api/v1/memory-packs/import/commit",
            headers=_key("pack-commit"),
            json=commit_payload,
        )
        assert committed.status_code == 200, committed.text
        assert committed.json()["inserted_count"] == 1
        commit_replay = client.post(
            "/api/v1/memory-packs/import/commit",
            headers=_key("pack-commit"),
            json=commit_payload,
        )
        assert commit_replay.status_code == 200
        assert commit_replay.json() == committed.json()

        imported = client.get("/api/v1/memories?source_type=import")
        assert imported.status_code == 200
        assert len(imported.json()["items"]) == 1
        assert imported.json()["items"][0]["status"] == "paused"
        factory = client.app.state.db_session_factory
        with factory() as session:
            snapshots = session.execute(select(IdempotencyKeyModel.response_json)).scalars()
            assert all(preview_body["preview_token"] not in item for item in snapshots)
    finally:
        client.close()
