"""Day 6 real-provider evaluator using only public REST APIs.

The application under test is treated as a black box.  This module deliberately
does not import ``memtrace_api`` or inspect its database.  Reports contain only
resource identifiers, controlled enums, token counts, latency, and failure
codes; prompts, memories, answers, evidence, API keys, and raw provider errors
are never written or printed.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEMANTIC_FIXTURE = PROJECT_ROOT / "fixtures/day6/semantic_cases.json"
DEFAULT_AB_FIXTURE = PROJECT_ROOT / "fixtures/day6/ab_cases.json"
PROMPT_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_CODE_RE = re.compile(r"[^A-Z0-9_]+")
PROVIDER_RETRY_DELAYS = (0.4, 1.2)


class GateFailure(RuntimeError):
    """A controlled failure that is safe to include in metadata-only output."""

    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        normalized = SAFE_CODE_RE.sub("_", code.upper()).strip("_")
        super().__init__(normalized[:128] or "UNKNOWN_FAILURE")
        self.code = normalized[:128] or "UNKNOWN_FAILURE"
        self.details = details or {}


def _provider_config(env_file: Path | None) -> tuple[str, str, str]:
    values: dict[str, str | None] = {}
    if env_file is not None:
        try:
            values = dict(dotenv_values(env_file))
        except OSError as exc:
            raise GateFailure("REAL_PROVIDER_ENV_FILE_UNREADABLE") from exc

    def setting(name: str, default: str = "") -> str:
        return (os.environ.get(name) or values.get(name) or default).strip()

    api_key = setting("LLM_API_KEY")
    if not api_key:
        key_file = setting("LLM_API_KEY_FILE")
        if key_file:
            try:
                api_key = Path(key_file).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise GateFailure("LLM_API_KEY_FILE_UNREADABLE") from exc
    if len(api_key.encode("utf-8")) > 16_384:
        raise GateFailure("LLM_API_KEY_INVALID")
    return (
        api_key,
        setting("LLM_MODEL"),
        setting("LLM_BASE_URL", "https://api.deepseek.com"),
    )


class RestClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        auth_mode: Literal["demo", "public"] = "demo",
        origin: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.auth_mode = auth_mode
        self.origin = origin
        self.csrf_token: str | None = None
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar)
        )

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        if self.csrf_token is not None and method not in {"GET", "HEAD", "OPTIONS"}:
            if self.origin is None:
                raise GateFailure("PUBLIC_ORIGIN_NOT_CONFIGURED")
            headers["Origin"] = self.origin
            headers["X-CSRF-Token"] = self.csrf_token
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                return response.status, _parse_json(raw)
        except urllib.error.HTTPError as exc:
            return exc.code, _parse_json(exc.read())
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise GateFailure("REST_TRANSPORT_ERROR") from exc

    def login(self, username: str, password: str) -> None:
        status, payload = self.request(
            "POST",
            "/api/v2/auth/login",
            {"username": username, "password": password},
        )
        if status != 200 or not isinstance(payload, dict):
            raise GateFailure("PUBLIC_LOGIN_FAILED")
        csrf = payload.get("csrf_token")
        if not isinstance(csrf, str) or len(csrf) < 32:
            raise GateFailure("PUBLIC_CSRF_MISSING")
        self.csrf_token = csrf

    def select_demo(self, alias: str) -> None:
        if self.auth_mode == "public":
            return
        _expect(
            self,
            "POST",
            "/api/v1/session/demo",
            status=200,
            body={"demo_alias": alias},
        )


def _parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateFailure("INVALID_JSON_RESPONSE") from exc


def _idem(label: str) -> str:
    return f"d6-{label}-{uuid.uuid4().hex}"


def _expect(
    client: RestClient,
    method: str,
    path: str,
    *,
    status: int,
    body: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> Any:
    actual, payload = client.request(
        method,
        path,
        body,
        idempotency_key=idempotency_key,
    )
    if actual != status:
        error_code = None
        safe_details: dict[str, Any] = {}
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            candidate = payload["error"].get("code")
            if isinstance(candidate, str):
                error_code = candidate
            retryable = payload["error"].get("retryable")
            if isinstance(retryable, bool):
                safe_details["retryable"] = retryable
            details = payload["error"].get("details")
            if isinstance(details, dict) and isinstance(
                details.get("provider_status"), int
            ):
                safe_details["provider_status"] = details["provider_status"]
        suffix = f"_{error_code}" if error_code else ""
        raise GateFailure(f"REST_{method}_{actual}{suffix}", safe_details)
    return payload


def _switch_user(client: RestClient, alias: str) -> None:
    client.select_demo(alias)


def _check_ready(client: RestClient) -> None:
    ready = _expect(client, "GET", "/api/v1/ready", status=200)
    if ready.get("status") != "ready":
        raise GateFailure("APPLICATION_NOT_READY")
    if ready.get("provider_mode") != "real":
        raise GateFailure("MOCK_FALLBACK")


def _create_task(client: RestClient, memory_mode: str) -> dict[str, Any]:
    task = _expect(
        client,
        "POST",
        "/api/v2/tasks",
        status=201,
        body={"memory_mode": memory_mode},
        idempotency_key=_idem("task"),
    )
    if task.get("provider_mode") != "real":
        raise GateFailure("TASK_PROVIDER_NOT_REAL")
    return task


def _run_turn(
    client: RestClient,
    task_id: str,
    content: str,
    *,
    memory_mode: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"content": content}
    if memory_mode is not None:
        body["memory_mode"] = memory_mode
    return _expect(
        client,
        "POST",
        f"/api/v2/tasks/{task_id}/turns",
        status=200,
        body=body,
        idempotency_key=_idem("turn"),
    )


def _wait_job(
    client: RestClient,
    job_id: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = _expect(
            client,
            "GET",
            f"/api/v2/reflection-jobs/{job_id}",
            status=200,
        )
        if job.get("status") == "completed":
            return job
        if job.get("status") == "failed":
            code = job.get("error_code")
            raise GateFailure(
                f"REFLECTION_{code}" if isinstance(code, str) else "REFLECTION_FAILED"
            )
        time.sleep(0.25)
    raise GateFailure("REFLECTION_TIMEOUT")


def _list_memories(client: RestClient) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(20):
        query = "?limit=100"
        if cursor:
            query += "&cursor=" + urllib.parse.quote(cursor, safe="")
        page = _expect(client, "GET", f"/api/v2/memories{query}", status=200)
        rows = page.get("items")
        if not isinstance(rows, list):
            raise GateFailure("INVALID_MEMORY_LIST")
        items.extend(item for item in rows if isinstance(item, dict))
        cursor = page.get("next_cursor")
        if cursor is None:
            return items
        if not isinstance(cursor, str):
            raise GateFailure("INVALID_MEMORY_CURSOR")
    raise GateFailure("MEMORY_PAGINATION_LIMIT")


def _memory_map(client: RestClient) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in _list_memories(client):
        memory_id = item.get("memory_id")
        if isinstance(memory_id, str):
            result[memory_id] = item
    return result


def _confirm_pending(client: RestClient, memory_ids: set[str]) -> None:
    current = _memory_map(client)
    for memory_id in sorted(memory_ids):
        item = current.get(memory_id)
        if item is not None and item.get("review_status") == "pending":
            _expect(
                client,
                "POST",
                f"/api/v2/memories/{memory_id}/confirm",
                status=200,
                idempotency_key=_idem("confirm"),
            )


def _cleanup_memories(client: RestClient, memory_ids: set[str]) -> None:
    current = _memory_map(client)
    for memory_id in sorted(memory_ids):
        item = current.get(memory_id)
        if item is None:
            continue
        state = item.get("review_status")
        if state == "pending":
            _expect(
                client,
                "POST",
                f"/api/v2/memories/{memory_id}/dismiss",
                status=200,
                idempotency_key=_idem("dismiss"),
            )
        elif state == "active":
            _expect(
                client,
                "POST",
                f"/api/v2/memories/{memory_id}/pause",
                status=200,
                idempotency_key=_idem("pause"),
            )


def _validate_usage(
    usage: Any,
    *,
    expected_model: str,
    required_stages: set[str],
) -> dict[str, int]:
    if not isinstance(usage, list) or not usage:
        raise GateFailure("MISSING_ACTUAL_USAGE")
    seen: set[str] = set()
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0}
    for item in usage:
        if not isinstance(item, dict):
            raise GateFailure("INVALID_USAGE_PROJECTION")
        stage = item.get("stage")
        if not isinstance(stage, str):
            raise GateFailure("INVALID_USAGE_STAGE")
        seen.add(stage)
        if item.get("provider_mode") != "real":
            raise GateFailure("MOCK_FALLBACK")
        if item.get("model") != expected_model:
            raise GateFailure("MODEL_MISMATCH")
        if not isinstance(item.get("prompt_hash"), str) or not PROMPT_HASH_RE.fullmatch(
            item["prompt_hash"]
        ):
            raise GateFailure("INVALID_PROMPT_HASH")
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            value = item.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise GateFailure("MISSING_ACTUAL_USAGE")
            totals[field] += value
        latency = item.get("latency_ms")
        if not isinstance(latency, int) or isinstance(latency, bool) or latency < 0:
            raise GateFailure("INVALID_LATENCY")
        totals["latency_ms"] += latency
    if not required_stages.issubset(seen):
        raise GateFailure("MISSING_REQUIRED_STAGE_USAGE")
    return totals


def _merge_totals(target: dict[str, int], source: dict[str, int]) -> None:
    for field in target:
        target[field] += source[field]


def _job_evidence(
    client: RestClient,
    job_id: str,
    *,
    expected_model: str,
) -> tuple[list[str], dict[str, int]]:
    judgments = _expect(
        client,
        "GET",
        f"/api/v2/reflection-jobs/{job_id}/judgments",
        status=200,
    )
    if not isinstance(judgments, list):
        raise GateFailure("INVALID_JUDGMENTS_RESPONSE")
    operations = [
        item.get("decision")
        for item in judgments
        if isinstance(item, dict) and isinstance(item.get("decision"), str)
    ]
    usage = _expect(
        client,
        "GET",
        f"/api/v2/reflection-jobs/{job_id}/usage",
        status=200,
    )
    required = {"reflection"}
    if operations:
        required.add("consolidation")
    totals = _validate_usage(
        usage,
        expected_model=expected_model,
        required_stages=required,
    )
    return operations, totals


def _wait_probe_job(
    client: RestClient,
    turn: dict[str, Any],
    *,
    timeout: float,
    expected_model: str,
) -> dict[str, int]:
    job_id = turn.get("reflection_job_id")
    if job_id is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_ms": 0,
        }
    if not isinstance(job_id, str):
        raise GateFailure("INVALID_REFLECTION_JOB_ID")
    _wait_job(client, job_id, timeout=timeout)
    _, totals = _job_evidence(client, job_id, expected_model=expected_model)
    return totals


@dataclass
class CaseOutcome:
    record: dict[str, Any]
    injected_expected: bool
    injected_actual: bool
    security_case: bool


def _evaluate_semantic_case(
    *,
    primary: RestClient,
    secondary: RestClient,
    case: dict[str, Any],
    repeat_index: int,
    poll_timeout: float,
    expected_model: str,
) -> CaseOutcome:
    del repeat_index
    _switch_user(primary, "blank_demo")
    baseline = _memory_map(primary)
    tracked: set[str] = set()
    resource_ids: dict[str, Any] = {
        "seed_task_ids": [],
        "job_ids": [],
        "memory_ids": [],
    }
    operations_by_seed: list[list[str]] = []
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0}
    phase = "setup"
    try:
        phase = "seed_task"
        seed_task = _create_task(primary, "on")
        resource_ids["seed_task_ids"].append(seed_task["task_id"])
        for seed in case["seed_turns"]:
            phase = "seed_chat"
            turn = _run_turn(primary, seed_task["task_id"], seed["content"])
            _merge_totals(
                totals,
                _validate_usage(
                    turn.get("usage"),
                    expected_model=expected_model,
                    required_stages={"chat"},
                ),
            )
            job_id = turn.get("reflection_job_id")
            if not isinstance(job_id, str):
                raise GateFailure("MISSING_REFLECTION_JOB")
            resource_ids["job_ids"].append(job_id)
            phase = "seed_reflection"
            job = _wait_job(
                primary,
                job_id,
                timeout=poll_timeout,
            )
            if job.get("provider_model") != expected_model:
                raise GateFailure("REFLECTION_MODEL_MISMATCH")
            phase = "seed_judgment_usage"
            operations, job_totals = _job_evidence(
                primary,
                job_id,
                expected_model=expected_model,
            )
            operations_by_seed.append(operations)
            _merge_totals(totals, job_totals)
            after = _memory_map(primary)
            tracked.update(set(after) - set(baseline))
            if seed.get("expect_memory"):
                if not operations_by_seed[-1]:
                    raise GateFailure("EXPECTED_MEMORY_NOT_EXTRACTED")
                _confirm_pending(primary, tracked)
            elif set(after) - set(baseline):
                raise GateFailure("UNEXPECTED_DURABLE_MEMORY")

        phase = "classification"
        final_memories = _memory_map(primary)
        tracked_kinds = sorted(
            {
                final_memories[memory_id]["kind"]
                for memory_id in tracked
                if memory_id in final_memories
            }
        )
        allowed_kinds = set(case.get("allowed_kinds", []))
        if tracked_kinds and not set(tracked_kinds).issubset(allowed_kinds):
            raise GateFailure(
                "MEMORY_KIND_OUTSIDE_ALLOWED_SET",
                {"actual_kinds": tracked_kinds},
            )
        allowed_operations = set(case.get("allowed_operations", []))
        last_operations = operations_by_seed[-1] if operations_by_seed else []
        if allowed_operations:
            if not last_operations or not set(last_operations).issubset(
                allowed_operations
            ):
                raise GateFailure(
                    "CONSOLIDATION_OUTSIDE_ALLOWED_SET",
                    {"actual_operations": last_operations},
                )
        elif any(operations_by_seed):
            raise GateFailure("UNEXPECTED_CONSOLIDATION")
        required_operations = set(case.get("required_operations", []))
        if not required_operations.issubset(last_operations):
            raise GateFailure(
                "REQUIRED_CONSOLIDATION_MISSING",
                {
                    "required_operations": sorted(required_operations),
                    "actual_operations": last_operations,
                },
            )

        probe_client = secondary if case.get("cross_owner_probe") else primary
        if case.get("cross_owner_probe"):
            phase = "owner_isolation"
            _switch_user(secondary, "seeded_demo")
            status, _ = secondary.request(
                "GET", f"/api/v2/tasks/{seed_task['task_id']}"
            )
            if status != 404:
                raise GateFailure("CROSS_OWNER_TASK_VISIBLE")
            for memory_id in tracked:
                status, _ = secondary.request("GET", f"/api/v2/memories/{memory_id}")
                if status != 404:
                    raise GateFailure("CROSS_OWNER_MEMORY_VISIBLE")
        phase = "probe_task"
        probe_baseline = _memory_map(probe_client)
        probe_task = _create_task(probe_client, case["probe_memory_mode"])
        resource_ids["probe_task_id"] = probe_task["task_id"]
        phase = "probe_chat"
        probe_turn = _run_turn(
            probe_client,
            probe_task["task_id"],
            case["probe"],
            memory_mode=case["probe_memory_mode"],
        )
        _merge_totals(
            totals,
            _validate_usage(
                probe_turn.get("usage"),
                expected_model=expected_model,
                required_stages={"chat"},
            ),
        )
        phase = "probe_reflection"
        _merge_totals(
            totals,
            _wait_probe_job(
                probe_client,
                probe_turn,
                timeout=poll_timeout,
                expected_model=expected_model,
            ),
        )
        probe_after = _memory_map(probe_client)
        probe_created = set(probe_after) - set(probe_baseline)
        if probe_created:
            _cleanup_memories(probe_client, probe_created)
            raise GateFailure("PROBE_CREATED_LONG_TERM_MEMORY")

        phase = "semantic_assertions"
        decisions = probe_turn.get("memory_decisions")
        if not isinstance(decisions, list):
            raise GateFailure("INVALID_MEMORY_DECISIONS")
        injected = [
            item
            for item in decisions
            if isinstance(item, dict) and item.get("injected")
        ]
        expected_injected = bool(case["expected_injected"])
        if expected_injected and not injected:
            raise GateFailure(
                "EXPECTED_INJECTION_MISSING",
                {
                    "applicability": [item.get("applicability") for item in decisions],
                    "reason_codes": [item.get("reason_code") for item in decisions],
                },
            )
        if not expected_injected and injected:
            raise GateFailure(
                "UNEXPECTED_INJECTION",
                {
                    "applicability": [item.get("applicability") for item in decisions],
                    "reason_codes": [item.get("reason_code") for item in decisions],
                },
            )
        expected_injected_count = case.get("expected_injected_count")
        if expected_injected_count is not None:
            if (
                not isinstance(expected_injected_count, int)
                or expected_injected_count < 0
            ):
                raise GateFailure("INVALID_EXPECTED_INJECTION_COUNT")
            if len(injected) != expected_injected_count:
                raise GateFailure(
                    "INJECTION_COUNT_MISMATCH",
                    {
                        "expected_count": expected_injected_count,
                        "actual_count": len(injected),
                    },
                )
        allowed_applicability = set(case.get("allowed_applicability", []))
        if decisions and any(
            item.get("applicability") not in allowed_applicability
            for item in decisions
            if isinstance(item, dict)
        ):
            raise GateFailure("APPLICABILITY_OUTSIDE_ALLOWED_SET")
        if not allowed_applicability and decisions:
            raise GateFailure("UNEXPECTED_APPLICABILITY_DECISION")
        required_applicability_counts = case.get("required_applicability_counts", {})
        if not isinstance(required_applicability_counts, dict):
            raise GateFailure("INVALID_APPLICABILITY_COUNTS")
        actual_applicability_counts = {
            value: sum(
                isinstance(item, dict) and item.get("applicability") == value
                for item in decisions
            )
            for value in required_applicability_counts
        }
        if any(
            not isinstance(expected, int)
            or expected < 0
            or actual_applicability_counts[value] != expected
            for value, expected in required_applicability_counts.items()
        ):
            raise GateFailure(
                "APPLICABILITY_COUNT_MISMATCH",
                {
                    "expected_counts": required_applicability_counts,
                    "actual_counts": actual_applicability_counts,
                },
            )
        allowed_effect = set(case.get("allowed_effect", []))
        for item in injected:
            if item.get("effect") not in allowed_effect:
                raise GateFailure(
                    "EFFECT_OUTSIDE_ALLOWED_SET",
                    {"actual_effect": item.get("effect")},
                )
            estimated = item.get("estimated_tokens")
            if not isinstance(estimated, int) or estimated > 100:
                raise GateFailure("PER_CARD_BUDGET_EXCEEDED")
        if sum(int(item.get("estimated_tokens", 0)) for item in injected) > 300:
            raise GateFailure("TOTAL_MEMORY_BUDGET_EXCEEDED")
        if any(item.get("memory_id") not in tracked for item in injected):
            raise GateFailure("UNEXPECTED_MEMORY_INJECTED")

        resource_ids["memory_ids"] = sorted(tracked)
        return CaseOutcome(
            record={
                "case_id": case["case_id"],
                "status": "passed",
                "resource_ids": resource_ids,
                "memory_kinds": tracked_kinds,
                "operations": operations_by_seed,
                "applicability": [item.get("applicability") for item in decisions],
                "expected_injected": expected_injected,
                "injected_actual": bool(injected),
                "injected_count": len(injected),
                "applicability_counts": actual_applicability_counts,
                "effects": [item.get("effect") for item in injected],
                "usage": totals,
            },
            injected_expected=expected_injected,
            injected_actual=bool(injected),
            security_case=bool(case.get("security_case")),
        )
    except GateFailure as exc:
        exc.details.setdefault("phase", phase)
        raise
    finally:
        _switch_user(primary, "blank_demo")
        _cleanup_memories(primary, tracked)


def _blind_judge(
    *,
    answer_a: str,
    answer_b: str,
    criterion: str,
    expected_model: str,
    base_url: str,
    api_key: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "winner": {"type": "string", "enum": ["A", "B", "tie"]},
            "criterion_met_a": {"type": "boolean"},
            "criterion_met_b": {"type": "boolean"},
            "critical_regression": {"type": "boolean"},
            "reason_code": {
                "type": "string",
                "enum": [
                    "criterion_clear_win",
                    "criterion_small_win",
                    "equivalent",
                    "both_fail",
                    "critical_regression",
                ],
            },
        },
        "required": [
            "winner",
            "criterion_met_a",
            "criterion_met_b",
            "critical_regression",
            "reason_code",
        ],
    }
    instructions = (
        "You are an independent blind evaluator. Compare Answer A and Answer B only "
        "against the supplied observable criterion. Do not infer which system produced "
        "either answer. Mark critical_regression true for a material factual, safety, or "
        "explicit-instruction regression. Call submit_blind_judgment exactly once with the "
        "five required judgment fields. Do not emit a prose answer."
    )
    payload = json.dumps(
        {"criterion": criterion, "answer_a": answer_a, "answer_b": answer_b},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    started = time.perf_counter()
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=120.0,
        max_retries=0,
    )
    try:
        data: dict[str, Any] | None = None
        for attempt in range(len(PROVIDER_RETRY_DELAYS) + 1):
            try:
                response = client.responses.create(
                    model=expected_model,
                    instructions=instructions,
                    input=payload,
                    max_output_tokens=512,
                    temperature=0.0,
                    reasoning={"effort": "none"},
                    tools=[
                        {
                            "type": "function",
                            "name": "submit_blind_judgment",
                            "description": "Submit the complete blind comparison result.",
                            "parameters": schema,
                        }
                    ],
                    tool_choice={
                        "type": "function",
                        "name": "submit_blind_judgment",
                    },
                )
                data = response.model_dump()
                break
            except (APIConnectionError, APITimeoutError) as exc:
                if attempt >= len(PROVIDER_RETRY_DELAYS):
                    raise GateFailure("BLIND_JUDGE_PROVIDER_ERROR") from exc
                time.sleep(PROVIDER_RETRY_DELAYS[attempt])
            except APIStatusError as exc:
                body = getattr(exc, "body", None)
                error = body.get("error", body) if isinstance(body, dict) else {}
                values = (
                    error.get("code") if isinstance(error, dict) else None,
                    error.get("type") if isinstance(error, dict) else None,
                )
                quota_failure = any(
                    isinstance(value, str) and "quota" in value.casefold()
                    for value in values
                )
                retryable = not quota_failure and (
                    exc.status_code in {408, 429} or 500 <= exc.status_code <= 599
                )
                if not retryable or attempt >= len(PROVIDER_RETRY_DELAYS):
                    raise GateFailure(
                        "BLIND_JUDGE_PROVIDER_ERROR",
                        {
                            "provider_status": exc.status_code,
                            "retryable": retryable,
                        },
                    ) from exc
                time.sleep(PROVIDER_RETRY_DELAYS[attempt])
            except Exception as exc:
                raise GateFailure("BLIND_JUDGE_PROVIDER_ERROR") from exc
        if data is None:  # pragma: no cover - loop either succeeds or raises
            raise GateFailure("BLIND_JUDGE_PROVIDER_ERROR")
    finally:
        client.close()
    if data.get("model") != expected_model:
        raise GateFailure("BLIND_JUDGE_MODEL_MISMATCH")
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise GateFailure("BLIND_JUDGE_MISSING_USAGE")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in (input_tokens, output_tokens, total_tokens)
    ):
        raise GateFailure("BLIND_JUDGE_MISSING_USAGE")
    calls = [
        item
        for item in data.get("output", [])
        if isinstance(item, dict)
        and item.get("type") == "function_call"
        and item.get("name") == "submit_blind_judgment"
    ]
    if len(calls) != 1 or not isinstance(calls[0].get("arguments"), str):
        raise GateFailure(
            "BLIND_JUDGE_TOOL_CALL_INVALID",
            {"matching_call_count": len(calls)},
        )
    raw = calls[0]["arguments"]
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateFailure("BLIND_JUDGE_INVALID_JSON") from exc
    expected_fields = set(schema["required"])
    if not isinstance(result, dict):
        raise GateFailure(
            "BLIND_JUDGE_SCHEMA_REJECTED",
            {"result_type": type(result).__name__},
        )
    actual_fields = set(result)
    if actual_fields != expected_fields:
        raise GateFailure(
            "BLIND_JUDGE_SCHEMA_REJECTED",
            {
                "missing_fields": sorted(expected_fields - actual_fields),
                "unexpected_field_count": len(actual_fields - expected_fields),
                "schema_definition_shape": {
                    "type",
                    "properties",
                    "required",
                }.issubset(actual_fields),
            },
        )
    if result.get("winner") not in {"A", "B", "tie"}:
        raise GateFailure("BLIND_JUDGE_SCHEMA_REJECTED")
    if result.get("reason_code") not in schema["properties"]["reason_code"]["enum"]:
        raise GateFailure("BLIND_JUDGE_SCHEMA_REJECTED")
    if any(
        not isinstance(result.get(field), bool)
        for field in ("criterion_met_a", "criterion_met_b", "critical_regression")
    ):
        raise GateFailure("BLIND_JUDGE_SCHEMA_REJECTED")
    return result, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
    }


def _evaluate_ab_case(
    *,
    client: RestClient,
    case: dict[str, Any],
    case_index: int,
    poll_timeout: float,
    expected_model: str,
    base_url: str,
    api_key: str,
) -> dict[str, Any]:
    _switch_user(client, "blank_demo")
    baseline = _memory_map(client)
    tracked: set[str] = set()
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0}
    try:
        seed_task = _create_task(client, "on")
        seed = _run_turn(
            client,
            seed_task["task_id"],
            "请把下面这条内容作为长期偏好或规则记住：" + case["memory"],
        )
        _merge_totals(
            totals,
            _validate_usage(
                seed.get("usage"),
                expected_model=expected_model,
                required_stages={"chat"},
            ),
        )
        job_id = seed.get("reflection_job_id")
        if not isinstance(job_id, str):
            raise GateFailure("MISSING_REFLECTION_JOB")
        _wait_job(client, job_id, timeout=poll_timeout)
        operations, job_totals = _job_evidence(
            client,
            job_id,
            expected_model=expected_model,
        )
        _merge_totals(totals, job_totals)
        if not operations:
            raise GateFailure("AB_MEMORY_NOT_EXTRACTED")
        after_seed = _memory_map(client)
        tracked.update(set(after_seed) - set(baseline))
        if not tracked:
            raise GateFailure("AB_MEMORY_NOT_PERSISTED")
        _confirm_pending(client, tracked)

        order: list[Literal["off", "on"]] = (
            ["off", "on"] if case_index % 2 == 0 else ["on", "off"]
        )
        answers: dict[str, str] = {}
        task_ids: dict[str, str] = {}
        for mode in order:
            probe_baseline = _memory_map(client)
            probe_task = _create_task(client, mode)
            task_ids[mode] = probe_task["task_id"]
            turn = _run_turn(
                client,
                probe_task["task_id"],
                case["probe"],
                memory_mode=mode,
            )
            _merge_totals(
                totals,
                _validate_usage(
                    turn.get("usage"),
                    expected_model=expected_model,
                    required_stages={"chat"},
                ),
            )
            if mode == "on" and not any(
                isinstance(item, dict) and item.get("injected")
                for item in turn.get("memory_decisions", [])
            ):
                raise GateFailure("AB_MEMORY_NOT_INJECTED")
            if mode == "off" and turn.get("memory_decisions"):
                raise GateFailure("AB_MEMORY_OFF_NOT_EMPTY")
            assistant = turn.get("assistant_message")
            if not isinstance(assistant, dict) or not isinstance(
                assistant.get("content"), str
            ):
                raise GateFailure("AB_ANSWER_MISSING")
            answers[mode] = assistant["content"]
            _merge_totals(
                totals,
                _wait_probe_job(
                    client,
                    turn,
                    timeout=poll_timeout,
                    expected_model=expected_model,
                ),
            )
            probe_created = set(_memory_map(client)) - set(probe_baseline)
            if probe_created:
                _cleanup_memories(client, probe_created)
                raise GateFailure("AB_PROBE_CREATED_LONG_TERM_MEMORY")

        on_is_a = case_index % 2 == 0
        judgment, judge_usage = _blind_judge(
            answer_a=answers["on"] if on_is_a else answers["off"],
            answer_b=answers["off"] if on_is_a else answers["on"],
            criterion=case["criterion"],
            expected_model=expected_model,
            base_url=base_url,
            api_key=api_key,
        )
        winner = judgment["winner"]
        mapped_winner = (
            "tie"
            if winner == "tie"
            else ("memory_on" if (winner == "A") == on_is_a else "memory_off")
        )
        return {
            "case_id": case["case_id"],
            "status": "passed",
            "resource_ids": {
                "seed_task_id": seed_task["task_id"],
                "job_id": job_id,
                "memory_ids": sorted(tracked),
                "probe_task_ids": task_ids,
            },
            "operation": operations,
            "run_order": order,
            "winner": mapped_winner,
            "criterion_met_memory_on": (
                judgment["criterion_met_a"] if on_is_a else judgment["criterion_met_b"]
            ),
            "criterion_met_memory_off": (
                judgment["criterion_met_b"] if on_is_a else judgment["criterion_met_a"]
            ),
            "critical_regression": judgment["critical_regression"],
            "reason_code": judgment["reason_code"],
            "workflow_usage": totals,
            "judge_usage": judge_usage,
        }
    finally:
        _cleanup_memories(client, tracked)


def _load_fixture(path: Path, *, expected_count: int) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateFailure("FIXTURE_INVALID") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "2.0.0"
        or payload.get("provider_requirement") != "real_only"
        or not isinstance(payload.get("cases"), list)
        or len(payload["cases"]) != expected_count
    ):
        raise GateFailure("FIXTURE_CONTRACT_MISMATCH")
    case_ids = [
        item.get("case_id") for item in payload["cases"] if isinstance(item, dict)
    ]
    if len(case_ids) != expected_count or len(set(case_ids)) != expected_count:
        raise GateFailure("FIXTURE_CASE_ID_INVALID")
    return payload["cases"]


def _selected(cases: list[dict[str, Any]], case_ids: set[str]) -> list[dict[str, Any]]:
    if not case_ids:
        return cases
    selected = [case for case in cases if case["case_id"] in case_ids]
    if {case["case_id"] for case in selected} != case_ids:
        raise GateFailure("UNKNOWN_CASE_ID")
    return selected


def _assert_clean_active_baseline(client: RestClient, alias: str) -> None:
    _switch_user(client, alias)
    active_count = sum(
        item.get("review_status") == "active" for item in _memory_map(client).values()
    )
    if active_count:
        raise GateFailure(
            "ACTIVE_MEMORY_BASELINE_NOT_EMPTY",
            {"demo_alias": alias, "active_count": active_count},
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate G5 through public APIs with a real DeepSeek provider"
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--mode", choices=("semantic", "ab", "all"), default="all")
    parser.add_argument(
        "--semantic-fixture", type=Path, default=DEFAULT_SEMANTIC_FIXTURE
    )
    parser.add_argument("--ab-fixture", type=Path, default=DEFAULT_AB_FIXTURE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--request-timeout", type=float, default=180.0)
    parser.add_argument("--poll-timeout", type=float, default=300.0)
    parser.add_argument("--auth-mode", choices=("demo", "public"), default="demo")
    parser.add_argument("--origin")
    parser.add_argument("--primary-username")
    parser.add_argument("--primary-password-file", type=Path)
    parser.add_argument("--secondary-username")
    parser.add_argument("--secondary-password-file", type=Path)
    parser.add_argument("--env-file", type=Path)
    return parser.parse_args()


def _read_credential(path: Path | None) -> str:
    if path is None:
        raise GateFailure("PUBLIC_CREDENTIAL_FILE_MISSING")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GateFailure("PUBLIC_CREDENTIAL_FILE_UNREADABLE") from exc
    if not value or len(value.encode()) > 1024:
        raise GateFailure("PUBLIC_CREDENTIAL_FILE_INVALID")
    return value


def main() -> int:
    args = parse_args()
    try:
        api_key, expected_model, base_url = _provider_config(args.env_file)
        config_failure: str | None = None
    except GateFailure as exc:
        api_key, expected_model, base_url = "", "", ""
        config_failure = exc.code
    report: dict[str, Any] = {
        "schema_version": "2.0.0",
        "runner": "day6-real-rest-only",
        "provider_mode": "real",
        "auth_mode": args.auth_mode,
        "has_llm_api_key": bool(api_key),
        "model": expected_model or None,
        "semantic": [],
        "ab": [],
    }
    exit_code = 0
    if config_failure or not api_key or not expected_model:
        report["failure_code"] = config_failure or "REAL_PROVIDER_NOT_CONFIGURED"
        exit_code = 2
    else:
        try:
            semantic_cases = _load_fixture(args.semantic_fixture, expected_count=16)
            ab_cases = _load_fixture(args.ab_fixture, expected_count=8)
            selected_ids = set(args.case_id)
            primary = RestClient(
                args.base_url,
                timeout=args.request_timeout,
                auth_mode=args.auth_mode,
                origin=args.origin,
            )
            secondary = RestClient(
                args.base_url,
                timeout=args.request_timeout,
                auth_mode=args.auth_mode,
                origin=args.origin,
            )
            if args.auth_mode == "public":
                if (
                    not args.origin
                    or not args.primary_username
                    or not args.secondary_username
                ):
                    raise GateFailure("PUBLIC_CREDENTIALS_NOT_CONFIGURED")
                primary.login(
                    args.primary_username,
                    _read_credential(args.primary_password_file),
                )
                secondary.login(
                    args.secondary_username,
                    _read_credential(args.secondary_password_file),
                )
            _check_ready(primary)
            _check_ready(secondary)
            _assert_clean_active_baseline(primary, "blank_demo")
            _assert_clean_active_baseline(secondary, "seeded_demo")
            if args.mode in {"semantic", "all"}:
                for case in _selected(semantic_cases, selected_ids):
                    for repeat_index in range(1, args.repeat + 1):
                        try:
                            outcome = _evaluate_semantic_case(
                                primary=primary,
                                secondary=secondary,
                                case=case,
                                repeat_index=repeat_index,
                                poll_timeout=args.poll_timeout,
                                expected_model=expected_model,
                            )
                            outcome.record["repeat"] = repeat_index
                            report["semantic"].append(outcome.record)
                        except GateFailure as exc:
                            failure = {
                                "case_id": case["case_id"],
                                "repeat": repeat_index,
                                "status": "failed",
                                "failure_code": exc.code,
                                "expected_injected": bool(case["expected_injected"]),
                            }
                            if exc.details:
                                failure["details"] = exc.details
                            report["semantic"].append(failure)
                            exit_code = 1
            if args.mode in {"ab", "all"}:
                if selected_ids:
                    ab_selected = [
                        case for case in ab_cases if case["case_id"] in selected_ids
                    ]
                else:
                    ab_selected = ab_cases
                for index, case in enumerate(ab_selected):
                    try:
                        report["ab"].append(
                            _evaluate_ab_case(
                                client=primary,
                                case=case,
                                case_index=index,
                                poll_timeout=args.poll_timeout,
                                expected_model=expected_model,
                                base_url=base_url,
                                api_key=api_key,
                            )
                        )
                    except GateFailure as exc:
                        failure = {
                            "case_id": case["case_id"],
                            "status": "failed",
                            "failure_code": exc.code,
                        }
                        if exc.details:
                            failure["details"] = exc.details
                        report["ab"].append(failure)
                        exit_code = 1
        except GateFailure as exc:
            report["failure_code"] = exc.code
            exit_code = 1

    semantic_rows = report["semantic"]
    semantic_passed = sum(item.get("status") == "passed" for item in semantic_rows)
    tp = sum(
        item.get("status") == "passed"
        and item.get("expected_injected") is True
        and item.get("injected_actual") is True
        for item in semantic_rows
    )
    fp = sum(
        item.get("failure_code") == "UNEXPECTED_INJECTION" for item in semantic_rows
    )
    precision = 1.0 if tp + fp == 0 else tp / (tp + fp)
    security_failures = sum(
        item.get("status") != "passed"
        for item in semantic_rows
        if item.get("case_id")
        in {"g5-13-prompt-injection-safe-reject", "g5-16-cross-owner-isolation"}
    )
    ab_rows = report["ab"]
    on_wins = sum(item.get("winner") == "memory_on" for item in ab_rows)
    critical_regressions = sum(
        bool(item.get("critical_regression")) for item in ab_rows
    )
    if semantic_rows and (precision < 0.95 or security_failures):
        exit_code = 1
    if (
        args.mode in {"ab", "all"}
        and not args.case_id
        and (on_wins < 6 or critical_regressions)
    ):
        exit_code = 1
    report["summary"] = {
        "overall_status": "passed" if exit_code == 0 else "failed",
        "run_failure_code": report.get("failure_code"),
        "semantic_total": len(semantic_rows),
        "semantic_passed": semantic_passed,
        "semantic_failed": len(semantic_rows) - semantic_passed,
        "activation_precision": round(precision, 4),
        "security_failures": security_failures,
        "ab_total": len(ab_rows),
        "ab_memory_on_wins": on_wins,
        "ab_critical_regressions": critical_regressions,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps(report["summary"], separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
