"""Day 7 unified v2 Memory Center, conflict, and Pack engineering tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import rfc8785

from test_day6_conversation import _client, _login, _wait_for_job


def _create_memory(
    client, *, task_key: str, turn_key: str, content: str
) -> tuple[str, dict[str, Any]]:
    task = client.post(
        "/api/v2/tasks",
        headers={"Idempotency-Key": task_key},
        json={"memory_mode": "on"},
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["task_id"]
    turn = client.post(
        f"/api/v2/tasks/{task_id}/turns",
        headers={"Idempotency-Key": turn_key},
        json={"content": content},
    )
    assert turn.status_code == 200, turn.text
    assert _wait_for_job(client, turn.json()["reflection_job_id"])["status"] == "completed"
    memories = client.get("/api/v2/memories?sort=oldest")
    assert memories.status_code == 200, memories.text
    return task_id, memories.json()["items"][-1]


def _pack_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _rehash_pack(value: dict[str, Any]) -> None:
    payload = {key: item for key, item in value.items() if key != "integrity"}
    value["integrity"]["canonical_payload_sha256"] = hashlib.sha256(
        rfc8785.dumps(payload)
    ).hexdigest()


def test_v2_versions_diff_restore_usage_owner_isolation_and_deletes(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    with client:
        _login(client)
        task_id, memory = _create_memory(
            client,
            task_key="d7-center-task-0001",
            turn_key="d7-center-turn-0001",
            content="以后回答我的解释类问题时，请先给结论。",
        )
        memory_id = memory["memory_id"]
        original_version_id = memory["current_version_id"]

        follow_up = client.post(
            f"/api/v2/tasks/{task_id}/turns",
            headers={"Idempotency-Key": "d7-center-turn-0002"},
            json={"content": "请解释闭包的用途。"},
        )
        assert follow_up.status_code == 200, follow_up.text
        usages = client.get(f"/api/v2/memories/{memory_id}/usages")
        assert usages.status_code == 200, usages.text
        assert len(usages.json()["items"]) == 1
        assert usages.json()["items"][0]["memory_id"] == memory_id

        edited = client.patch(
            f"/api/v2/memories/{memory_id}",
            headers={"Idempotency-Key": "d7-center-edit-0001"},
            json={
                "kind": "rule",
                "content": "解释技术概念时先给一句结论",
                "applies_when": "用户请求解释技术概念时",
                "expected_current_version_id": original_version_id,
            },
        )
        assert edited.status_code == 200, edited.text
        edited_memory = edited.json()["memory"]
        edited_version_id = edited_memory["current_version_id"]
        assert edited_memory["version"] == 2

        diff = client.get(
            f"/api/v2/memories/{memory_id}/version-diff",
            params={"from_version_id": original_version_id, "to_version_id": edited_version_id},
        )
        assert diff.status_code == 200, diff.text
        assert {"kind", "content", "applies_when"} <= set(diff.json()["changed_fields"])

        restored = client.post(
            f"/api/v2/memories/{memory_id}/versions/restore",
            headers={"Idempotency-Key": "d7-center-restore-version-0001"},
            json={
                "source_version_id": original_version_id,
                "expected_current_version_id": edited_version_id,
            },
        )
        assert restored.status_code == 200, restored.text
        restored_memory = restored.json()["memory"]
        assert restored_memory["version"] == 3
        assert restored_memory["current_version_id"] not in {
            original_version_id,
            edited_version_id,
        }

        relations = client.get(f"/api/v2/memories/{memory_id}/relations")
        assert relations.status_code == 200
        assert relations.json()["items"] == []

        _login(client, "seeded_demo")
        assert client.get(f"/api/v2/memories/{memory_id}").status_code == 404
        assert client.get(f"/api/v2/memories/{memory_id}/usages").status_code == 404
        _login(client)

        source_deleted = client.request(
            "DELETE",
            f"/api/v2/tasks/{task_id}",
            headers={"Idempotency-Key": "d7-center-delete-source-0001"},
            json={
                "confirm_task_id": task_id,
                "memory_policy": "preserve_and_mark_evidence_missing",
            },
        )
        assert source_deleted.status_code == 200, source_deleted.text
        assert source_deleted.json()["affected_memory_count"] == 1
        assert client.get(f"/api/v2/tasks/{task_id}").status_code == 404
        detail = client.get(f"/api/v2/memories/{memory_id}")
        assert detail.status_code == 200
        assert detail.json()["evidence"] == []

        current = detail.json()["memory"]
        deleted = client.request(
            "DELETE",
            f"/api/v2/memories/{memory_id}",
            headers={"Idempotency-Key": "d7-center-delete-memory-0001"},
            json={
                "expected_current_version_id": current["current_version_id"],
                "confirm_content": current["content"],
            },
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "deleted"
        replay = client.request(
            "DELETE",
            f"/api/v2/memories/{memory_id}",
            headers={"Idempotency-Key": "d7-center-delete-memory-0001"},
            json={
                "expected_current_version_id": current["current_version_id"],
                "confirm_content": current["content"],
            },
        )
        assert replay.json() == deleted.json()
        assert client.get(f"/api/v2/memories/{memory_id}").status_code == 404

        owner_events = client.get("/api/v2/memory-events", params={"after_seq": 0})
        assert owner_events.status_code == 200, owner_events.text
        deletion_events = [
            item
            for item in owner_events.json()["items"]
            if item["event_type"] == "memory.deleted" and item["memory_id"] == memory_id
        ]
        assert len(deletion_events) == 1
        assert deletion_events[0]["old_status"] == current["review_status"]
        assert deletion_events[0]["new_status"] == "deleted"
        assert deletion_events[0]["reason_code"] == "user_permanent_delete"
        assert set(deletion_events[0]) == {
            "event_id",
            "event_seq",
            "event_type",
            "memory_id",
            "version_id",
            "old_status",
            "new_status",
            "reason_code",
            "job_id",
            "created_at",
        }


@pytest.mark.parametrize("action", ["prefer", "separate_scopes", "merge", "pause_both"])
def test_v2_conflict_actions_are_atomic_and_user_controlled(tmp_path: Path, action: str) -> None:
    client, _, _ = _client(tmp_path)
    with client:
        _login(client)
        _, left = _create_memory(
            client,
            task_key=f"d7-conflict-{action}-task-1",
            turn_key=f"d7-conflict-{action}-turn-1",
            content="以后解释代码时，请先给结论。",
        )
        _, right = _create_memory(
            client,
            task_key=f"d7-conflict-{action}-task-2",
            turn_key=f"d7-conflict-{action}-turn-2",
            content="以后解释算法时，请先给详细推导。",
        )
        created = client.post(
            "/api/v2/memory-conflicts",
            headers={"Idempotency-Key": f"d7-conflict-{action}-create"},
            json={
                "left_memory_id": left["memory_id"],
                "left_expected_current_version_id": left["current_version_id"],
                "right_memory_id": right["memory_id"],
                "right_expected_current_version_id": right["current_version_id"],
            },
        )
        assert created.status_code == 200, created.text
        relation_id = created.json()["relation"]["relation_id"]
        request: dict[str, Any] = {
            "expected_relation_status": "unresolved",
            "left_expected_current_version_id": left["current_version_id"],
            "right_expected_current_version_id": right["current_version_id"],
            "action": action,
        }
        if action == "prefer":
            request["preferred_memory_id"] = left["memory_id"]
        elif action == "separate_scopes":
            request["left_applies_when"] = "仅解释具体代码实现时"
            request["right_applies_when"] = "仅解释抽象算法原理时"
        elif action == "merge":
            request["merged_memory"] = {
                "kind": "preference",
                "content": "先给结论，再根据问题复杂度补充必要推导",
                "applies_when": "解释代码或算法问题时",
            }
        resolved = client.post(
            f"/api/v2/memory-conflicts/{relation_id}/resolve",
            headers={"Idempotency-Key": f"d7-conflict-{action}-resolve"},
            json=request,
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["action"] == action
        assert resolved.json()["status"] == "resolved"
        if action == "merge":
            merged_id = resolved.json()["resolution_memory_id"]
            assert merged_id not in {left["memory_id"], right["memory_id"]}
            merged = client.get(f"/api/v2/memories/{merged_id}").json()["memory"]
            assert merged["content"] == request["merged_memory"]["content"]
        detail = client.get(f"/api/v2/memory-conflicts/{relation_id}")
        assert detail.status_code == 200
        assert detail.json()["relation"]["status"] == "resolved"


def test_v2_repeated_conflict_after_resolution_returns_controlled_409(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    with client:
        _login(client)
        _, left = _create_memory(
            client,
            task_key="d7-conflict-repeat-task-1",
            turn_key="d7-conflict-repeat-turn-1",
            content="以后解释代码时，请先给结论。",
        )
        _, right = _create_memory(
            client,
            task_key="d7-conflict-repeat-task-2",
            turn_key="d7-conflict-repeat-turn-2",
            content="以后解释算法时，请先给详细推导。",
        )
        request = {
            "left_memory_id": left["memory_id"],
            "left_expected_current_version_id": left["current_version_id"],
            "right_memory_id": right["memory_id"],
            "right_expected_current_version_id": right["current_version_id"],
        }
        created = client.post(
            "/api/v2/memory-conflicts",
            headers={"Idempotency-Key": "d7-conflict-repeat-create-1"},
            json=request,
        )
        assert created.status_code == 200, created.text
        relation_id = created.json()["relation"]["relation_id"]
        resolved = client.post(
            f"/api/v2/memory-conflicts/{relation_id}/resolve",
            headers={"Idempotency-Key": "d7-conflict-repeat-resolve"},
            json={
                "expected_relation_status": "unresolved",
                "left_expected_current_version_id": left["current_version_id"],
                "right_expected_current_version_id": right["current_version_id"],
                "action": "separate_scopes",
                "left_applies_when": "仅解释具体代码实现时",
                "right_applies_when": "仅解释抽象算法原理时",
            },
        )
        assert resolved.status_code == 200, resolved.text
        left_after = client.get(f"/api/v2/memories/{left['memory_id']}").json()["memory"]
        right_after = client.get(f"/api/v2/memories/{right['memory_id']}").json()["memory"]
        repeated = client.post(
            "/api/v2/memory-conflicts",
            headers={"Idempotency-Key": "d7-conflict-repeat-create-2"},
            json={
                "left_memory_id": left_after["memory_id"],
                "left_expected_current_version_id": left_after["current_version_id"],
                "right_memory_id": right_after["memory_id"],
                "right_expected_current_version_id": right_after["current_version_id"],
            },
        )
        assert repeated.status_code == 409, repeated.text
        assert repeated.json()["error"]["code"] == "MEMORY_STATE_CONFLICT"


def test_memory_pack_v2_round_trip_idempotency_security_and_owner_isolation(
    tmp_path: Path,
) -> None:
    client, _, _ = _client(tmp_path)
    with client:
        _login(client)
        _, memory = _create_memory(
            client,
            task_key="d7-pack-task-0001",
            turn_key="d7-pack-turn-0001",
            content="以后解释技术概念时，请先给简短结论。",
        )
        exported = client.post(
            "/api/v2/memory-packs/export",
            headers={"Idempotency-Key": "d7-pack-export-0001"},
            json={
                "memory_ids": [memory["memory_id"]],
                "name": "Synthetic v2 export",
                "description": "Contract and security test only.",
            },
        )
        assert exported.status_code == 200, exported.text
        pack = exported.json()
        rendered = json.dumps(pack)
        all_keys: set[str] = set()

        def collect_keys(value: object) -> None:
            if isinstance(value, dict):
                all_keys.update(value)
                for child in value.values():
                    collect_keys(child)
            elif isinstance(value, list):
                for child in value:
                    collect_keys(child)

        collect_keys(pack)
        assert pack["format_version"] == "2.0.0"
        assert pack["cards"][0]["external_id"].startswith("card_")
        assert memory["memory_id"] not in rendered
        assert {"owner_id", "task_id", "message_id", "evidence"}.isdisjoint(all_keys)

        duplicate = client.post(
            "/api/v2/memory-packs/import/preview",
            headers={
                "Idempotency-Key": "d7-pack-preview-duplicate",
                "Content-Type": "application/json",
            },
            content=_pack_bytes(pack),
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["duplicate_count"] == 1
        assert duplicate.json()["legal_new_count"] == 0

        changed_same_key = json.loads(json.dumps(pack))
        changed_same_key["name"] = "Changed request under same key"
        _rehash_pack(changed_same_key)
        conflict = client.post(
            "/api/v2/memory-packs/import/preview",
            headers={
                "Idempotency-Key": "d7-pack-preview-duplicate",
                "Content-Type": "application/json",
            },
            content=_pack_bytes(changed_same_key),
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

        raw = _pack_bytes(pack).decode("utf-8")
        duplicate_key_raw = raw.replace(
            '"format":"memtrace-memory-pack"',
            '"format":"memtrace-memory-pack","format":"memtrace-memory-pack"',
            1,
        ).encode("utf-8")
        duplicate_key = client.post(
            "/api/v2/memory-packs/import/preview",
            headers={"Idempotency-Key": "d7-pack-preview-bad-key"},
            content=duplicate_key_raw,
        )
        assert duplicate_key.status_code == 422
        assert duplicate_key.json()["error"]["code"] == "MEMORY_PACK_INVALID"

        tampered = json.loads(json.dumps(pack))
        tampered["cards"][0]["content"] = "被篡改但未重算完整性哈希"
        integrity = client.post(
            "/api/v2/memory-packs/import/preview",
            headers={"Idempotency-Key": "d7-pack-preview-bad-integrity"},
            content=_pack_bytes(tampered),
        )
        assert integrity.status_code == 422
        assert integrity.json()["error"]["code"] == "MEMORY_PACK_INTEGRITY_MISMATCH"

        suspicious = json.loads(json.dumps(pack))
        suspicious["cards"][0]["content"] = "<script>alert('synthetic')</script>"
        _rehash_pack(suspicious)
        suspicious_preview = client.post(
            "/api/v2/memory-packs/import/preview",
            headers={"Idempotency-Key": "d7-pack-preview-suspicious"},
            content=_pack_bytes(suspicious),
        )
        assert suspicious_preview.status_code == 200, suspicious_preview.text
        assert suspicious_preview.json()["suspicious_count"] == 1

        _login(client, "seeded_demo")
        preview = client.post(
            "/api/v2/memory-packs/import/preview",
            headers={"Idempotency-Key": "d7-pack-preview-import"},
            content=_pack_bytes(pack),
        )
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["legal_new_count"] == 1
        assert len(preview_body["preview_token"]) == 43

        _login(client)
        hidden = client.post(
            "/api/v2/memory-packs/import/commit",
            headers={"Idempotency-Key": "d7-pack-cross-owner"},
            json={
                "batch_id": preview_body["batch_id"],
                "preview_token": preview_body["preview_token"],
                "mode": "import_all_paused",
            },
        )
        assert hidden.status_code == 404

        _login(client, "seeded_demo")
        committed = client.post(
            "/api/v2/memory-packs/import/commit",
            headers={"Idempotency-Key": "d7-pack-commit-import"},
            json={
                "batch_id": preview_body["batch_id"],
                "preview_token": preview_body["preview_token"],
                "mode": "import_all_paused",
            },
        )
        assert committed.status_code == 200, committed.text
        assert committed.json()["inserted_count"] == 1
        imported = client.get("/api/v2/memories?source=import").json()["items"]
        assert len(imported) == 1
        assert imported[0]["review_status"] == "paused"
        assert imported[0]["source_type"] == "import"
