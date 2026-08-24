"""Run a content-redacted G1 Provider smoke against an already-running API."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin

import httpx

ProviderMode = Literal["mock", "real"]
SAFE_TASK_TEXT = "def add(a, b): return a + b"


class SmokeFailure(RuntimeError):
    """A safe, user-facing failure that never contains response content."""


@dataclass(frozen=True)
class SseFrame:
    event_type: str
    payload: dict[str, Any]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def iter_sse_frames(response: httpx.Response) -> Iterator[SseFrame]:
    event_type: str | None = None
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line == "":
            if event_type is not None:
                require(bool(data_lines), "SSE frame has no data field")
                try:
                    payload = json.loads("\n".join(data_lines))
                except json.JSONDecodeError as exc:
                    raise SmokeFailure("SSE data is not valid JSON") from exc
                require(isinstance(payload, dict), "SSE data is not a JSON object")
                yield SseFrame(event_type=event_type, payload=payload)
            event_type = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_type = line.removeprefix("event:").strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())
    require(
        event_type is None and not data_lines, "SSE stream ended with a partial frame"
    )


def safe_json(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise SmokeFailure(f"{label} is not valid JSON") from exc
    require(isinstance(payload, dict), f"{label} is not a JSON object")
    return payload


def run_smoke(
    *,
    base_url: str,
    expected_mode: ProviderMode,
    timeout_seconds: float,
) -> dict[str, Any]:
    normalized_base = base_url.rstrip("/") + "/"
    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 15.0))
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        ready_response = client.get(urljoin(normalized_base, "api/v1/ready"))
        require(ready_response.status_code == 200, "ready endpoint did not return 200")
        ready = safe_json(ready_response, "ready response")
        require(ready.get("status") == "ready", "API is not ready")
        require(
            ready.get("provider_mode") == expected_mode,
            "ready provider mode does not match the requested gate",
        )

        session_response = client.post(
            urljoin(normalized_base, "api/v1/session/demo"),
            json={"demo_alias": "blank_demo"},
        )
        require(session_response.status_code == 200, "demo session did not return 200")

        create_response = client.post(
            urljoin(normalized_base, "api/v1/tasks"),
            headers={"Idempotency-Key": f"real-provider-smoke-{uuid.uuid4().hex}"},
            json={
                "task_text": SAFE_TASK_TEXT,
                "memory_mode": "on",
                "current_constraints": {
                    "response_policy": "default",
                    "urgency": "normal",
                    "memory_disabled": False,
                    "source": "ui",
                },
            },
        )
        require(create_response.status_code == 202, "task creation did not return 202")
        accepted = safe_json(create_response, "task creation response")
        task_id = accepted.get("task_id")
        run_id = accepted.get("run_id")
        events_url = accepted.get("events_url")
        require(
            isinstance(task_id, str) and task_id.startswith("task_"), "invalid task ID"
        )
        require(isinstance(run_id, str) and run_id.startswith("run_"), "invalid run ID")
        require(
            isinstance(events_url, str) and events_url.startswith("/api/"),
            "invalid events URL",
        )
        require(
            accepted.get("provider_mode") == expected_mode,
            "accepted provider mode mismatch",
        )

        event_types: list[str] = []
        persistent_sequence = 0
        next_chunk_sequence = 1
        output = ""
        end_offset = 0
        metrics: dict[str, Any] | None = None
        saw_done = False
        with client.stream(
            "GET", urljoin(normalized_base, events_url.lstrip("/"))
        ) as stream:
            require(stream.status_code == 200, "SSE endpoint did not return 200")
            require(
                stream.headers.get("content-type", "").startswith("text/event-stream"),
                "SSE endpoint returned the wrong content type",
            )
            for frame in iter_sse_frames(stream):
                payload = frame.payload
                require(
                    payload.get("event_type") == frame.event_type,
                    "SSE wire and payload event mismatch",
                )
                require(payload.get("task_id") == task_id, "SSE task ID mismatch")
                require(payload.get("run_id") == run_id, "SSE run ID mismatch")
                require(
                    "reasoning_content" not in json.dumps(payload),
                    "private reasoning leaked into SSE",
                )
                event_sequence = payload.get("event_seq")
                if event_sequence is not None:
                    require(
                        isinstance(event_sequence, int)
                        and event_sequence == persistent_sequence + 1,
                        "persistent SSE sequence is not contiguous",
                    )
                    persistent_sequence = event_sequence
                event_types.append(frame.event_type)

                if frame.event_type == "agent.chunk":
                    data = payload.get("data")
                    require(isinstance(data, dict), "agent.chunk data is missing")
                    delta = data.get("delta")
                    require(
                        isinstance(delta, str) and delta, "agent.chunk delta is empty"
                    )
                    require(
                        data.get("chunk_seq") == next_chunk_sequence,
                        "chunk sequence is not contiguous",
                    )
                    require(
                        data.get("start_offset") == end_offset,
                        "chunk start offset is not contiguous",
                    )
                    expected_end = end_offset + len(delta.encode("utf-8"))
                    require(
                        data.get("end_offset") == expected_end,
                        "chunk UTF-8 end offset is invalid",
                    )
                    output += delta
                    end_offset = expected_end
                    next_chunk_sequence += 1
                elif frame.event_type == "run.metrics":
                    data = payload.get("data")
                    require(isinstance(data, dict), "run.metrics data is missing")
                    metrics = data
                elif frame.event_type in {"run.failed", "error"}:
                    data = payload.get("data")
                    error_code = (
                        data.get("error_code") if isinstance(data, dict) else None
                    )
                    if error_code is None and isinstance(data, dict):
                        error_code = data.get("code")
                    safe_code = error_code if isinstance(error_code, str) else "UNKNOWN"
                    raise SmokeFailure(
                        f"Provider run failed with safe code {safe_code}"
                    )
                elif frame.event_type == "stream.done":
                    saw_done = True
                    break

        required_events = {
            "task.created",
            "task.stage",
            "task.fingerprinted",
            "memory.retrieval.started",
            "agent.plan.published",
            "tool.called",
            "tool.result",
            "agent.chunk",
            "run.metrics",
            "run.completed",
            "stream.done",
        }
        require(
            required_events.issubset(event_types),
            "successful Provider trace is incomplete",
        )
        require(saw_done, "successful Provider trace has no stream.done")
        require(bool(output), "successful Provider trace has no answer chunks")
        require(metrics is not None, "successful Provider trace has no metrics")
        require(
            metrics.get("provider_mode") == expected_mode,
            "metrics provider mode mismatch",
        )
        expected_token_sources = (
            {"mock"} if expected_mode == "mock" else {"actual", "unavailable"}
        )
        require(
            metrics.get("token_source") in expected_token_sources,
            "metrics token source mismatch",
        )
        require(
            isinstance(metrics.get("model"), str) and metrics.get("model"),
            "metrics model is missing",
        )

        snapshot_response = client.get(
            urljoin(normalized_base, f"api/v1/tasks/{task_id}")
        )
        require(
            snapshot_response.status_code == 200, "final snapshot did not return 200"
        )
        snapshot = safe_json(snapshot_response, "final snapshot")
        require(
            snapshot.get("task_id") == task_id and snapshot.get("run_id") == run_id,
            "snapshot IDs mismatch",
        )
        require(snapshot.get("terminal") is True, "final snapshot is not terminal")
        require(
            snapshot.get("run_status") == "succeeded", "final snapshot did not succeed"
        )
        require(
            snapshot.get("end_offset") == end_offset,
            "snapshot end offset differs from SSE",
        )
        require(
            snapshot.get("partial_output") == output, "snapshot output differs from SSE"
        )
        final_message = snapshot.get("final_message")
        require(
            isinstance(final_message, dict) and final_message.get("content") == output,
            "snapshot final message differs from SSE",
        )

        return {
            "task_id": task_id,
            "run_id": run_id,
            "provider_mode": expected_mode,
            "model": metrics.get("model"),
            "status": "succeeded",
            "prompt_tokens": metrics.get("prompt_tokens"),
            "output_tokens": metrics.get("output_tokens"),
            "token_source": metrics.get("token_source"),
            "first_token_ms": metrics.get("first_token_ms"),
            "total_ms": metrics.get("total_ms"),
            "end_offset": end_offset,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate one G1 Provider stream without printing task or answer content."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--expected-mode", choices=("mock", "real"), default="real")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0 or args.timeout_seconds > 300:
        print(
            "FAIL: timeout must be greater than 0 and at most 300 seconds",
            file=sys.stderr,
        )
        return 2
    try:
        summary = run_smoke(
            base_url=args.base_url,
            expected_mode=args.expected_mode,
            timeout_seconds=args.timeout_seconds,
        )
    except SmokeFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"FAIL: HTTP transport error ({type(exc).__name__})", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - final output-redaction boundary
        print(f"FAIL: unexpected smoke error ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
