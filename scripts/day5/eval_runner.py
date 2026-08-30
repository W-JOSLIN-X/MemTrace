"""Day 5 REST-only G4 evaluator; imports no MemTrace backend modules."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import rfc8785


class RestClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar)
        )

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | bytes | None = None,
        *,
        key: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers = {"Accept": "application/json"}
        data = None
        if isinstance(body, dict):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif isinstance(body, bytes):
            data = body
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def write(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | bytes,
        key: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return self.request(method, path, body, key=key or f"d5-eval-{uuid.uuid4()}")


def require(status: int, expected: int, label: str, body: dict[str, Any]) -> None:
    if status != expected:
        code = body.get("error", {}).get("code", "UNCONTROLLED")
        raise RuntimeError(f"{label}_{status}_{code}")


def wait_terminal(client: RestClient, path: str, terminal: set[str]) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status, body = client.request("GET", path)
        if status == 200 and (body.get("status") in terminal or body.get("terminal")):
            return body
        time.sleep(0.05)
    raise RuntimeError("WAIT_TIMEOUT")


def switch_user(client: RestClient, alias: str) -> None:
    status, body = client.request("POST", "/api/v1/session/demo", {"demo_alias": alias})
    require(status, 200, "SESSION", body)


def provision_active(client: RestClient, serial: str) -> dict[str, Any]:
    status, accepted = client.write(
        "POST",
        "/api/v1/tasks",
        {
            "task_text": f"请解释 Python 调试检查点 {serial}。",
            "memory_mode": "on",
            "current_constraints": {
                "response_policy": "guided_hint",
                "urgency": "normal",
                "memory_disabled": False,
                "source": "ui",
            },
        },
    )
    require(status, 202, "TASK", accepted)
    snapshot = wait_terminal(
        client, f"/api/v1/tasks/{accepted['task_id']}", {"succeeded", "failed"}
    )
    if snapshot.get("run_status") != "succeeded":
        error = snapshot.get("error")
        code = (
            error.get("code", "UNCONTROLLED")
            if isinstance(error, dict)
            else "UNCONTROLLED"
        )
        raise RuntimeError(f"TASK_RUN_FAILED_{code}")
    status, feedback = client.write(
        "POST",
        f"/api/v1/tasks/{snapshot['task_id']}/feedback",
        {
            "explicit_text": f"以后处理 Python 调试检查点 {serial} 时，先给一个诊断动作，再解释答案。"
        },
    )
    require(status, 202, "FEEDBACK", feedback)
    job = wait_terminal(
        client,
        f"/api/v1/memory-jobs/{feedback['memory_job_id']}",
        {"completed", "failed"},
    )
    if job.get("status") != "completed" or not job.get("candidate_ids"):
        raise RuntimeError("CANDIDATE_MISSING")
    status, resolved = client.write(
        "POST",
        f"/api/v1/memory-candidates/{job['candidate_ids'][0]}/resolve",
        {"action": "accept"},
    )
    require(status, 200, "ACCEPT", resolved)
    return resolved["card"]


def conflict_request(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        "left_memory_id": left["memory_id"],
        "left_expected_current_version_id": left["current_version_id"],
        "right_memory_id": right["memory_id"],
        "right_expected_current_version_id": right["current_version_id"],
    }


def merged_input(serial: str, scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "preference",
        "title": f"用户填写合并卡 {serial}",
        "rule": f"用户确认的合并规则 {serial}：必须先执行诊断动作，再根据结果逐步解释完整答案。",
        "avoid": "",
        "trigger_text": "Python 调试",
        "scope": scope,
        "exceptions": [],
    }


def run_conflicts(
    client: RestClient, cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        left = provision_active(client, f"c{index}-left")
        right = provision_active(client, f"c{index}-right")
        ids = {
            "left_memory_id": left["memory_id"],
            "right_memory_id": right["memory_id"],
        }
        if case["operation"] == "manual_merge":
            status, body = client.write(
                "POST",
                "/api/v1/memories/merge",
                {
                    **conflict_request(left, right),
                    "merged_card": merged_input(str(index), left["scope"]),
                },
            )
            require(status, 200, case["id"], body)
            ids["merged_memory_id"] = body["merged_memory_id"]
        else:
            status, detected = client.write(
                "POST", "/api/v1/memory-conflicts", conflict_request(left, right)
            )
            require(status, 200, f"{case['id']}_DETECT", detected)
            ids["relation_id"] = detected["relation_id"]
            if case["operation"] == "owner_isolation":
                switch_user(client, "seeded_demo")
                status, body = client.request(
                    "GET", f"/api/v1/memory-conflicts/{detected['relation_id']}"
                )
                require(status, 404, case["id"], body)
                switch_user(client, "blank_demo")
            else:
                resolve = {
                    "expected_relation_status": "unresolved",
                    "left_expected_current_version_id": left["current_version_id"],
                    "right_expected_current_version_id": right["current_version_id"],
                    "action": case["action"],
                }
                if case["action"] == "prefer":
                    resolve["preferred_memory_id"] = left["memory_id"]
                if case["action"] == "separate_scopes":
                    resolve["left_scope"] = {
                        **left["scope"],
                        "level": "project",
                        "project_key": f"left-{index}",
                    }
                    resolve["right_scope"] = {
                        **right["scope"],
                        "level": "project",
                        "project_key": f"right-{index}",
                    }
                if case["action"] == "merge":
                    resolve["merged_card"] = merged_input(str(index), left["scope"])
                if case["operation"] == "stale_version":
                    status, edited = client.write(
                        "PATCH",
                        f"/api/v1/memories/{left['memory_id']}",
                        {
                            "expected_current_version_id": left["current_version_id"],
                            "patch": {
                                "rule": f"stale guard {index} must create a new immutable version before conflict resolution"
                            },
                        },
                    )
                    require(status, 200, f"{case['id']}_EDIT", edited)
                    expected_status = 409
                else:
                    expected_status = 200
                idem = f"d5-eval-replay-{uuid.uuid4()}"
                status, body = client.write(
                    "POST",
                    f"/api/v1/memory-conflicts/{detected['relation_id']}/resolve",
                    resolve,
                    idem,
                )
                require(status, expected_status, case["id"], body)
                if case["operation"] == "idempotent_replay":
                    replay_status, replay = client.write(
                        "POST",
                        f"/api/v1/memory-conflicts/{detected['relation_id']}/resolve",
                        resolve,
                        idem,
                    )
                    require(replay_status, 200, f"{case['id']}_REPLAY", replay)
                    if replay != body:
                        raise RuntimeError("REPLAY_RESPONSE_DRIFT")
        results.append(
            {
                "case_id": case["id"],
                "resource_ids": ids,
                "reason_codes": [],
                "counts": {},
                "failure_code": None,
            }
        )
    return results


def canonical_bytes(pack: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in pack.items() if key != "integrity"}
    pack["integrity"] = {
        "algorithm": "sha256",
        "canonical_payload_sha256": hashlib.sha256(rfc8785.dumps(payload)).hexdigest(),
    }
    return json.dumps(pack, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def error_code(body: dict[str, Any]) -> str | None:
    return body.get("error", {}).get("code")


def preview(client: RestClient, payload: bytes) -> tuple[int, dict[str, Any]]:
    return client.write("POST", "/api/v1/memory-packs/import/preview", payload)


def run_pack(client: RestClient, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = provision_active(client, "pack-source")
    status, exported = client.write(
        "POST",
        "/api/v1/memory-packs/export",
        {"memory_ids": [active["memory_id"]], "name": "G4 eval", "description": ""},
    )
    require(status, 200, "PACK_EXPORT", exported)
    base_bytes = json.dumps(exported, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    switch_user(client, "seeded_demo")
    results: list[dict[str, Any]] = []
    for case in cases:
        operation = case["operation"]
        payload = json.loads(base_bytes)
        status = 0
        body: dict[str, Any] = {}
        if operation == "oversized_file":
            status, body = preview(client, b"{" + b" " * (1024 * 1024 + 1))
        elif operation == "duplicate_keys":
            status, body = preview(client, b'{"format":"x","format":"y"}')
        elif operation == "unsupported_version":
            payload["format_version"] = "9.0.0"
            status, body = preview(client, canonical_bytes(payload))
        elif operation == "integrity_mismatch":
            payload["name"] = "tampered"
            status, body = preview(client, json.dumps(payload).encode())
        elif operation == "dangling_relation":
            payload["relations"] = [
                {
                    "from_external_id": payload["cards"][0]["external_id"],
                    "to_external_id": "card_missing",
                    "relation_type": "reinforces",
                }
            ]
            status, body = preview(client, canonical_bytes(payload))
        elif operation == "self_relation":
            ext = payload["cards"][0]["external_id"]
            payload["relations"] = [
                {
                    "from_external_id": ext,
                    "to_external_id": ext,
                    "relation_type": "reinforces",
                }
            ]
            status, body = preview(client, canonical_bytes(payload))
        elif operation == "forbidden_field":
            payload["cards"][0]["system_prompt"] = "forbidden"
            status, body = preview(client, canonical_bytes(payload))
        elif operation == "xss_text":
            payload["cards"][0]["rule"] = "<script>alert(1)</script>"
            status, body = preview(client, canonical_bytes(payload))
            require(status, 200, case["id"], body)
            assert body["items"][0]["classification"] == "suspicious"
        elif operation in {
            "round_trip",
            "cross_owner_batch",
            "expired_commit",
            "tampered_token",
        }:
            status, body = preview(client, base_bytes)
            require(status, 200, f"{case['id']}_PREVIEW", body)
            batch = body["batch_id"]
            token = body["preview_token"]
            if operation == "cross_owner_batch":
                switch_user(client, "blank_demo")
                status, body = client.request(
                    "GET", f"/api/v1/memory-packs/import/{batch}"
                )
                switch_user(client, "seeded_demo")
            else:
                if operation == "expired_commit":
                    expiry = (
                        datetime.fromisoformat(
                            body["pack_metadata"].get(
                                "expires_at", "1970-01-01T00:00:00+00:00"
                            )
                        )
                        if "expires_at" in body["pack_metadata"]
                        else None
                    )
                    del expiry
                    time.sleep(2.2)
                if operation == "tampered_token":
                    token = token[:-1] + ("A" if token[-1] != "A" else "B")
                status, body = client.write(
                    "POST",
                    "/api/v1/memory-packs/import/commit",
                    {
                        "batch_id": batch,
                        "preview_token": token,
                        "mode": "import_all_paused",
                    },
                )
        expected = case["expected"]
        if "http_status" in expected:
            require(status, expected["http_status"], case["id"], body)
        if (
            expected.get("failure_code")
            and error_code(body) != expected["failure_code"]
        ):
            raise RuntimeError(f"{case['id']}_CODE_{error_code(body)}")
        if operation == "round_trip":
            require(status, 200, case["id"], body)
            list_status, page = client.request(
                "GET", "/api/v1/memories?status=paused&source_type=import"
            )
            require(list_status, 200, f"{case['id']}_LIST", page)
            if not page["items"]:
                raise RuntimeError("ROUND_TRIP_IMPORT_MISSING")
        results.append(
            {
                "case_id": case["id"],
                "resource_ids": {"batch_id": body.get("batch_id")},
                "reason_codes": [
                    item.get("reason")
                    for item in body.get("items", [])
                    if item.get("reason")
                ],
                "counts": {
                    key: body.get(key)
                    for key in ("inserted_count", "skipped_count", "warning_count")
                    if key in body
                },
                "failure_code": error_code(body),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    conflicts = json.loads(
        (root / "fixtures/day5/g4_conflict_cases.json").read_text(encoding="utf-8")
    )["cases"]
    packs = json.loads(
        (root / "fixtures/day5/g4_pack_security_cases.json").read_text(encoding="utf-8")
    )["cases"]
    client = RestClient(args.base_url)
    switch_user(client, "blank_demo")
    results = run_conflicts(client, conflicts) + run_pack(client, packs)
    output = {
        "contract_version": "1.4.0",
        "runner": "day5-rest-only",
        "case_count": len(results),
        "passed": len(results),
        "failed": 0,
        "results": results,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "failed", "failure_code": str(exc)}, separators=(",", ":")
            )
        )
        raise SystemExit(1) from exc
