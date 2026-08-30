"""Day 4 REST-only G3 evaluator; imports no backend implementation modules."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class RestClient:
    def __init__(
        self,
        base_url: str,
        *,
        origin: str | None = None,
        public_identities: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.origin = origin
        self.csrf_token: str | None = None
        self.public_identities = public_identities or {}
        self.public_sessions: dict[str, tuple[urllib.request.OpenerDirector, str]] = {}
        self.opener = self._new_opener()

    @staticmethod
    def _new_opener() -> urllib.request.OpenerDirector:
        jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar)
        )

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        idempotent: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotent:
            headers["Idempotency-Key"] = f"d4-eval-{uuid.uuid4()}"
        if self.csrf_token is not None and method not in {"GET", "HEAD", "OPTIONS"}:
            if self.origin is None:
                raise RuntimeError("PUBLIC_ORIGIN_NOT_CONFIGURED")
            headers["Origin"] = self.origin
            headers["X-CSRF-Token"] = self.csrf_token
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def select_identity(self, alias: str) -> None:
        credentials = self.public_identities.get(alias)
        if credentials is None:
            status, _ = self.request(
                "POST", "/api/v1/session/demo", {"demo_alias": alias}
            )
            if status != 200:
                raise RuntimeError(f"SESSION_{status}")
            return
        cached = self.public_sessions.get(alias)
        if cached is not None:
            self.opener, self.csrf_token = cached
            return
        self.opener = self._new_opener()
        self.csrf_token = None
        username, password = credentials
        status, payload = self.request(
            "POST",
            "/api/v2/auth/login",
            {"username": username, "password": password},
        )
        csrf_token = payload.get("csrf_token") if isinstance(payload, dict) else None
        if status != 200 or not isinstance(csrf_token, str) or len(csrf_token) < 32:
            raise RuntimeError("PUBLIC_LOGIN_FAILED")
        self.csrf_token = csrf_token
        self.public_sessions[alias] = (self.opener, csrf_token)


def read_credential(path: Path | None) -> str:
    if path is None:
        raise RuntimeError("PUBLIC_CREDENTIAL_FILE_MISSING")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("PUBLIC_CREDENTIAL_FILE_UNREADABLE") from exc
    if not value or len(value.encode("utf-8")) > 1024:
        raise RuntimeError("PUBLIC_CREDENTIAL_FILE_INVALID")
    return value


def wait_task(client: RestClient, task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status, snapshot = client.request("GET", f"/api/v1/tasks/{task_id}")
        if status == 200 and snapshot.get("terminal"):
            return snapshot
        time.sleep(0.05)
    raise RuntimeError("TASK_TIMEOUT")


def create_task(client: RestClient, case: dict[str, Any]) -> dict[str, Any]:
    status, accepted = client.request(
        "POST",
        "/api/v1/tasks",
        {
            "task_text": case["task_text"],
            "memory_mode": case.get("memory_mode", "on"),
            "current_constraints": {
                "response_policy": case.get("response_policy", "default"),
                "urgency": "normal",
                "memory_disabled": case.get("memory_mode", "on") == "off",
                "source": "ui",
            },
        },
        idempotent=True,
    )
    if status != 202:
        raise RuntimeError(f"TASK_CREATE_{status}")
    return wait_task(client, accepted["task_id"])


def wait_job(client: RestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status, job = client.request("GET", f"/api/v1/memory-jobs/{job_id}")
        if status == 200 and job.get("status") in {"completed", "failed"}:
            return job
        time.sleep(0.05)
    raise RuntimeError("MEMORY_JOB_TIMEOUT")


def provision_active_memory(
    client: RestClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = create_task(
        client,
        {
            "task_text": "请解释 Python 递归调试时如何观察终止条件。",
            "memory_mode": "on",
            "response_policy": "guided_hint",
        },
    )
    status, accepted = client.request(
        "POST",
        f"/api/v1/tasks/{source['task_id']}/feedback",
        {
            "explicit_text": "以后解释 Python 递归调试时，先提醒我检查终止条件，再给完整答案。"
        },
        idempotent=True,
    )
    if status != 202:
        raise RuntimeError(f"FEEDBACK_{status}")
    job = wait_job(client, accepted["memory_job_id"])
    if job.get("status") != "completed" or not job.get("candidate_ids"):
        raise RuntimeError("CANDIDATE_MISSING")
    memory_id = job["candidate_ids"][0]
    status, resolved = client.request(
        "POST",
        f"/api/v1/memory-candidates/{memory_id}/resolve",
        {"action": "accept"},
        idempotent=True,
    )
    if status != 200:
        raise RuntimeError(f"ACCEPT_{status}")
    card = resolved["card"]
    status, detail = client.request(
        "PATCH",
        f"/api/v1/memories/{memory_id}",
        {
            "expected_current_version_id": card["current_version_id"],
            "patch": {
                "rule": source["fingerprint"]["semantic_query"],
                "exceptions": ["response_policy:direct_fix"],
            },
        },
        idempotent=True,
    )
    if status != 200:
        raise RuntimeError(f"EDIT_{status}")
    return detail["card"], source


def pause_existing_active_memories(client: RestClient) -> None:
    """Make repeated evaluator runs deterministic inside the dedicated gate owner."""
    status, page = client.request("GET", "/api/v1/memories?status=active")
    if status != 200:
        raise RuntimeError(f"ACTIVE_LIST_{status}")
    for card in page.get("items", []):
        pause_status, _ = client.request(
            "POST",
            f"/api/v1/memories/{card['memory_id']}/pause",
            {"expected_current_version_id": card["current_version_id"]},
            idempotent=True,
        )
        if pause_status != 200:
            raise RuntimeError(f"ACTIVE_PAUSE_{pause_status}")


def trace_result(case_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    trace = snapshot.get("retrieval_trace") or {}
    usages = snapshot.get("memory_usages") or []
    return {
        "case_id": case_id,
        "resource_ids": {
            "task_id": snapshot.get("task_id"),
            "run_id": snapshot.get("run_id"),
            "trace_id": trace.get("retrieval_trace_id"),
            "usage_ids": [usage.get("usage_id") for usage in usages],
        },
        "reason_codes": trace.get("reason_codes", [])
        + [
            reason
            for decision in trace.get("decisions", [])
            for reason in decision["reason_codes"]
        ],
        "scores": [
            decision.get("final_score") for decision in trace.get("decisions", [])
        ],
        "counts": {
            key: trace.get(key, 0)
            for key in (
                "candidate_count",
                "retrieved_count",
                "selected_count",
                "injected_count",
            )
        },
        "tokens": {
            "estimated": trace.get("memory_tokens_estimated", 0),
            "actual": trace.get("provider_prompt_tokens_actual"),
        },
        "latency_ms": trace.get("retrieval_ms"),
        "verification": [usage.get("verification_status") for usage in usages],
        "failure_code": None,
    }


def check_expected(case: dict[str, Any], result: dict[str, Any]) -> None:
    expected = case["expected"]
    counts = result["counts"]
    mappings = {
        "selected_min": counts["selected_count"] >= expected.get("selected_min", 0),
        "injected_min": counts["injected_count"] >= expected.get("injected_min", 0),
        "selected_max": counts["selected_count"] <= expected.get("selected_max", 10**9),
        "injected_max": counts["injected_count"] <= expected.get("injected_max", 10**9),
        "candidate_max": counts["candidate_count"]
        <= expected.get("candidate_max", 10**9),
    }
    for key, passed in mappings.items():
        if key in expected and not passed:
            raise RuntimeError(f"EXPECT_{key.upper()}")
    if "reason" in expected and expected["reason"] not in result["reason_codes"]:
        raise RuntimeError("EXPECT_REASON")
    if "single_memory_tokens_max" in expected and any(
        token > expected["single_memory_tokens_max"]
        for token in result.get("usage_tokens", [])
    ):
        raise RuntimeError("EXPECT_SINGLE_BUDGET")
    if (
        "total_memory_tokens_max" in expected
        and result["tokens"]["estimated"] > expected["total_memory_tokens_max"]
    ):
        raise RuntimeError("EXPECT_TOTAL_BUDGET")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "fixtures/day4/g3_retrieval_cases.json",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--auth-mode", choices=("demo", "public"), default="demo")
    parser.add_argument("--origin")
    parser.add_argument("--primary-username")
    parser.add_argument("--primary-password-file", type=Path)
    parser.add_argument("--secondary-username")
    parser.add_argument("--secondary-password-file", type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    public_identities: dict[str, tuple[str, str]] = {}
    if args.auth_mode == "public":
        if not args.origin or not args.primary_username or not args.secondary_username:
            print(json.dumps({"failure_code": "PUBLIC_CREDENTIALS_NOT_CONFIGURED"}))
            return 1
        public_identities = {
            "blank_demo": (
                args.primary_username,
                read_credential(args.primary_password_file),
            ),
            "seeded_demo": (
                args.secondary_username,
                read_credential(args.secondary_password_file),
            ),
        }
    client = RestClient(
        args.base_url,
        origin=args.origin,
        public_identities=public_identities,
    )
    try:
        client.select_identity("blank_demo")
    except RuntimeError as exc:
        print(json.dumps({"failure_code": str(exc)}))
        return 1
    try:
        pause_existing_active_memories(client)
        card, source = provision_active_memory(client)
    except RuntimeError as exc:
        print(json.dumps({"failure_code": str(exc)}))
        return 1

    last_positive: dict[str, Any] | None = None
    results: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        try:
            operation = case["operation"]
            if operation == "pause":
                status, paused = client.request(
                    "POST",
                    f"/api/v1/memories/{card['memory_id']}/pause",
                    {"expected_current_version_id": card["current_version_id"]},
                    idempotent=True,
                )
                if status != 200:
                    raise RuntimeError(f"PAUSE_{status}")
                card = paused["card"]
                snapshot = create_task(
                    client,
                    {
                        "task_text": source["task_text"],
                        "memory_mode": "on",
                        "response_policy": "guided_hint",
                    },
                )
                status, resumed = client.request(
                    "POST",
                    f"/api/v1/memories/{card['memory_id']}/resume",
                    {"expected_current_version_id": card["current_version_id"]},
                    idempotent=True,
                )
                if status != 200:
                    raise RuntimeError(f"RESUME_{status}")
                card = resumed["card"]
            elif operation == "resume":
                status, paused = client.request(
                    "POST",
                    f"/api/v1/memories/{card['memory_id']}/pause",
                    {"expected_current_version_id": card["current_version_id"]},
                    idempotent=True,
                )
                if status != 200:
                    raise RuntimeError(f"PAUSE_{status}")
                status, resumed = client.request(
                    "POST",
                    f"/api/v1/memories/{card['memory_id']}/resume",
                    {
                        "expected_current_version_id": paused["card"][
                            "current_version_id"
                        ]
                    },
                    idempotent=True,
                )
                if status != 200:
                    raise RuntimeError(f"RESUME_{status}")
                card = resumed["card"]
                snapshot = create_task(
                    client,
                    {
                        "task_text": source["task_text"],
                        "memory_mode": "on",
                        "response_policy": "guided_hint",
                    },
                )
            elif operation == "status_filter":
                status, paused = client.request(
                    "POST",
                    f"/api/v1/memories/{card['memory_id']}/pause",
                    {"expected_current_version_id": card["current_version_id"]},
                    idempotent=True,
                )
                if status != 200:
                    raise RuntimeError(f"PAUSE_{status}")
                card = paused["card"]
                snapshot = create_task(
                    client,
                    {
                        "task_text": source["task_text"],
                        "memory_mode": "on",
                        "response_policy": "guided_hint",
                    },
                )
                status, resumed = client.request(
                    "POST",
                    f"/api/v1/memories/{card['memory_id']}/resume",
                    {"expected_current_version_id": card["current_version_id"]},
                    idempotent=True,
                )
                if status != 200:
                    raise RuntimeError(f"RESUME_{status}")
                card = resumed["card"]
            elif operation == "owner_isolation":
                assert last_positive is not None
                client.select_identity("seeded_demo")
                cross_status, _ = client.request(
                    "GET", f"/api/v1/tasks/{last_positive['task_id']}"
                )
                client.select_identity("blank_demo")
                if cross_status != 404:
                    raise RuntimeError("OWNER_ISOLATION")
                result = {
                    "case_id": case["id"],
                    "resource_ids": {},
                    "reason_codes": [],
                    "scores": [],
                    "counts": {},
                    "tokens": {},
                    "latency_ms": 0,
                    "verification": [],
                    "failure_code": None,
                }
                results.append(result)
                continue
            elif operation in {
                "budget_single",
                "budget_total",
                "hash",
                "recovery",
                "verifier",
            }:
                if last_positive is None:
                    raise RuntimeError("POSITIVE_PREREQUISITE")
                snapshot = last_positive
            else:
                snapshot = create_task(client, case)
            result = trace_result(case["id"], snapshot)
            result["usage_tokens"] = [
                usage["estimated_tokens"] for usage in snapshot.get("memory_usages", [])
            ]
            if operation == "hash":
                prompt_hash = snapshot["retrieval_trace"]["prompt_section_hash"]
                if (
                    not isinstance(prompt_hash, str)
                    or len(prompt_hash) != hashlib.sha256().digest_size * 2
                ):
                    raise RuntimeError("EXPECT_HASH")
            if operation == "recovery":
                task_status, recovered = client.request(
                    "GET", f"/api/v1/tasks/{snapshot['task_id']}"
                )
                if (
                    task_status != 200
                    or not recovered.get("retrieval_trace")
                    or not recovered.get("memory_usages")
                ):
                    raise RuntimeError("EXPECT_RECOVERY")
            if operation == "verifier" and not result["verification"]:
                raise RuntimeError("EXPECT_VERIFIER")
            check_expected(case, result)
            if result["counts"].get("injected_count", 0) > 0:
                last_positive = snapshot
            result.pop("usage_tokens", None)
            results.append(result)
        except (RuntimeError, KeyError, AssertionError) as exc:
            results.append(
                {
                    "case_id": case["id"],
                    "resource_ids": {},
                    "reason_codes": [],
                    "scores": [],
                    "counts": {},
                    "tokens": {},
                    "latency_ms": None,
                    "verification": [],
                    "failure_code": str(exc),
                }
            )

    report = {
        "fixture_version": fixture["fixture_version"],
        "case_count": len(results),
        "passed": sum(item["failure_code"] is None for item in results),
        "failed": sum(item["failure_code"] is not None for item in results),
        "results": results,
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
