#!/usr/bin/env python3
"""REST-only Day 3 G2 evaluator.

The runner intentionally does not import ``memtrace_api``. It exercises the
public HTTP contract with an isolated demo session and writes metadata-only
results: fixture ids, controlled classifications/dispositions, counts, and
pass/fail reasons. Task text, feedback text, edits, rules, and evidence quotes
are never copied to the result file or console.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ApiFailure(Exception):
    status: int | None
    code: str


class Client:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            code = f"HTTP_{error.code}"
            try:
                payload = json.loads(error.read().decode("utf-8"))
                parsed = payload.get("error", {}).get("code")
                if isinstance(parsed, str):
                    code = parsed
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            raise ApiFailure(error.code, code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ApiFailure(None, "NETWORK_ERROR") from None
        if not isinstance(value, dict):
            raise ApiFailure(None, "INVALID_RESPONSE")
        return value


def stable_key(prefix: str, fixture_id: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{fixture_id}".encode()).hexdigest()[:32]
    return f"eval-{prefix}-{digest}"


def poll(
    client: Client,
    path: str,
    *,
    terminal: set[str],
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    delay = 0.05
    while True:
        value = client.request("GET", path)
        status = value.get("status") or value.get("run_status")
        if status in terminal or value.get("terminal") is True:
            return value
        if time.monotonic() >= deadline:
            raise ApiFailure(None, "EVAL_POLL_TIMEOUT")
        time.sleep(delay)
        delay = min(0.5, delay * 2)


def scope_at_or_below(actual: str, ceiling: str) -> bool:
    rank = {"session": 0, "task_family": 1, "project": 2, "global": 3}
    return actual in rank and ceiling in rank and rank[actual] <= rank[ceiling]


def evaluate_entry(
    client: Client,
    entry: dict[str, Any],
    default_request: dict[str, Any],
    poll_timeout: float,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    fixture_id = str(entry["id"])
    task_body = {"task_text": entry["task_text"], **default_request}
    accepted = client.request(
        "POST",
        "/api/v1/tasks",
        body=task_body,
        idempotency_key=stable_key("task", fixture_id),
    )
    task_id = accepted["task_id"]
    snapshot = poll(
        client,
        f"/api/v1/tasks/{urllib.parse.quote(task_id)}",
        terminal={"succeeded", "failed"},
        timeout=poll_timeout,
    )
    if snapshot.get("run_status") != "succeeded":
        raise ApiFailure(None, "TASK_DID_NOT_SUCCEED")

    feedback_body = {key: value for key, value in entry["feedback"].items() if value is not None}
    feedback = client.request(
        "POST",
        f"/api/v1/tasks/{urllib.parse.quote(task_id)}/feedback",
        body=feedback_body,
        idempotency_key=stable_key("feedback", fixture_id),
    )
    job_id = feedback["memory_job_id"]
    job = poll(
        client,
        f"/api/v1/memory-jobs/{urllib.parse.quote(job_id)}",
        terminal={"completed", "failed"},
        timeout=poll_timeout,
    )
    candidate_ids = job.get("candidate_ids", [])
    details = [
        client.request("GET", f"/api/v1/memories/{urllib.parse.quote(memory_id)}")
        for memory_id in candidate_ids
    ]
    expected = entry["expected"]
    fingerprint = snapshot.get("fingerprint") or {}
    actual = {
        "domain": fingerprint.get("domain"),
        "task_type": fingerprint.get("task_type"),
        "job_status": job.get("status"),
        "disposition": job.get("disposition"),
        "candidate_count": len(candidate_ids),
        "candidate_kinds": [detail.get("card", {}).get("kind") for detail in details],
        "job_error_code": job.get("error_code"),
    }
    mismatches: list[str] = []
    expected_fingerprint = entry["expected_fingerprint"]
    for key in ("domain", "task_type"):
        if actual[key] != expected_fingerprint[key]:
            mismatches.append(f"{key}_mismatch")
    for key in (
        "job_status",
        "disposition",
        "candidate_count",
        "candidate_kinds",
        "job_error_code",
    ):
        if actual[key] != expected[key]:
            mismatches.append(f"{key}_mismatch")
    ceiling = expected.get("max_scope_level")
    if ceiling is not None:
        for detail in details:
            level = detail.get("card", {}).get("scope", {}).get("level")
            if not isinstance(level, str) or not scope_at_or_below(level, ceiling):
                mismatches.append("scope_ceiling_exceeded")
                break
    result = {
        "id": fixture_id,
        "passed": not mismatches,
        "mismatches": sorted(set(mismatches)),
        "actual": actual,
    }

    smoke: dict[str, Any] | None = None
    if fixture_id == "d3-001-zh-durable-preference-language" and candidate_ids:
        memory_id = candidate_ids[0]
        resolved = client.request(
            "POST",
            f"/api/v1/memory-candidates/{urllib.parse.quote(memory_id)}/resolve",
            body={"action": "edit_accept", "patch": {"avoid": ""}},
            idempotency_key=stable_key("resolve", fixture_id),
        )
        card = resolved.get("card", {})
        smoke = {
            "id": "durable_edit_accept_active_v1",
            "passed": (
                resolved.get("action") == "edit_accept"
                and resolved.get("new_status") == "active"
                and card.get("version") == 1
                and isinstance(resolved.get("memory_version_id"), str)
            ),
        }
    elif fixture_id == "d3-008-zh-one-shot-rush":
        smoke = {
            "id": "one_shot_episode_only_zero_candidates",
            "passed": (job.get("disposition") == "episode_only" and len(candidate_ids) == 0),
        }
    return result, smoke


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Day 3 G2 via public REST APIs")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--request-timeout", type=float, default=10.0)
    parser.add_argument("--poll-timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    client = Client(args.base_url, args.request_timeout)
    report: dict[str, Any] = {
        "report_version": "1.0",
        "contract_version": fixture.get("contract_version"),
        "fixture_review_status": fixture.get("review_status"),
        "entries": [],
        "smoke": [],
    }
    exit_code = 0
    try:
        client.request("POST", "/api/v1/session/demo", body={"demo_alias": "blank_demo"})
        for entry in fixture["entries"]:
            try:
                result, smoke = evaluate_entry(
                    client,
                    entry,
                    fixture["default_request"],
                    args.poll_timeout,
                )
            except ApiFailure as error:
                result = {
                    "id": str(entry.get("id", "unknown")),
                    "passed": False,
                    "mismatches": [error.code],
                    "actual": {},
                }
                smoke = None
            report["entries"].append(result)
            if smoke is not None:
                report["smoke"].append(smoke)
            if not result["passed"] or (smoke is not None and not smoke["passed"]):
                exit_code = 1
    except ApiFailure as error:
        report["setup_error"] = error.code
        exit_code = 1

    report["summary"] = {
        "total": len(report["entries"]),
        "passed": sum(1 for item in report["entries"] if item["passed"]),
        "failed": sum(1 for item in report["entries"] if not item["passed"]),
        "smoke_passed": sum(1 for item in report["smoke"] if item["passed"]),
        "smoke_total": len(report["smoke"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = report["summary"]
    print(
        "G2 eval: "
        f"{summary['passed']}/{summary['total']} fixtures, "
        f"{summary['smoke_passed']}/{summary['smoke_total']} smoke checks"
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
