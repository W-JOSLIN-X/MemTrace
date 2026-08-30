"""Run all six real DeepSeek release preflight checks without printing content."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_SRC = PROJECT_ROOT / "apps" / "api" / "src"
sys.path.insert(0, str(API_SRC))

from memtrace_api.config import Settings
from memtrace_api.providers import DeepSeekProvider, ProviderFailure, ProviderRequest


def _emit(report: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _usage(payload: dict[str, object]) -> dict[str, int]:
    value = payload.get("usage")
    if not isinstance(value, dict):
        raise TypeError("actual usage is missing")
    result: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        item = value.get(key)
        if not isinstance(item, int) or item < 0:
            raise ValueError("actual usage is invalid")
        result[key] = item
    if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
        raise ValueError("actual usage totals are inconsistent")
    return result


async def _run(output: Path | None = None) -> int:
    settings = Settings()
    report: dict[str, object] = {
        "provider_mode": settings.provider_mode,
        "has_llm_api_key": settings.has_llm_api_key,
        "base_url": settings.llm_base_url,
        "configured_model": settings.llm_model,
        "checks": {},
    }
    checks = report["checks"]
    assert isinstance(checks, dict)
    if settings.mock_mode or not settings.has_llm_api_key:
        report["error_code"] = "REAL_PROVIDER_NOT_CONFIGURED"
        _emit(report, output)
        return 2
    if settings.llm_api_key is None:  # pragma: no cover - narrowed above
        raise RuntimeError("unreachable missing key")

    headers = {
        "Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/") + "/",
            headers=headers,
            timeout=settings.provider_timeout_seconds,
        ) as client:
            models_response = await client.get("models")
            if models_response.status_code != 200:
                raise ValueError("model list did not return 200")
            model_payload = models_response.json()
            available = sorted(
                item["id"]
                for item in model_payload.get("data", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            )
            if settings.llm_model not in available:
                report["available_models"] = available
                raise ValueError("configured model is unavailable")
            checks["model_list"] = {"status": "passed", "model_available": True}

            minimal_response = await client.post(
                "responses",
                json={
                    "model": settings.llm_model,
                    "instructions": "Reply briefly and safely.",
                    "input": "Return a short acknowledgement.",
                    "max_output_tokens": 64,
                    "reasoning": {"effort": "none"},
                },
            )
            if minimal_response.status_code != 200:
                raise ValueError("minimal Responses request did not return 200")
            minimal = minimal_response.json()
            if (
                minimal.get("status") != "completed"
                or minimal.get("model") != settings.llm_model
            ):
                raise ValueError("minimal Responses terminal metadata is invalid")
            minimal_usage = _usage(minimal)
            checks["minimal_response"] = {"status": "passed", **minimal_usage}
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
        report["error_code"] = "OFFICIAL_API_PREFLIGHT_FAILED"
        report["failure_stage"] = "model_list_or_minimal_response"
        report["failure_type"] = type(exc).__name__
        _emit(report, output)
        return 3

    provider = DeepSeekProvider(settings)
    try:
        delta_count = 0
        stream_usage = None
        stream_model = None
        async for item in provider.stream(
            ProviderRequest(task_text="Return one short acknowledgement.", stage="chat")
        ):
            if item.delta:
                delta_count += 1
            if item.usage is not None:
                stream_usage = item.usage
                stream_model = item.model
        if (
            delta_count < 1
            or stream_usage is None
            or stream_model != settings.llm_model
        ):
            raise ValueError("stream did not produce visible deltas and terminal usage")
        checks["streaming"] = {
            "status": "passed",
            "delta_count": delta_count,
            "input_tokens": stream_usage.prompt_tokens,
            "output_tokens": stream_usage.output_tokens,
            "total_tokens": stream_usage.total_tokens,
        }

        schema = {
            "name": "day7_preflight",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"ok": {"type": "boolean", "const": True}},
                "required": ["ok"],
            },
        }
        structured = await provider.complete_json(
            ProviderRequest(
                task_text='Return the required object with "ok" set to true.',
                output_schema=schema,
                stage="reflection",
            ),
            schema,
        )
        if structured.parsed != {"ok": True} or structured.model != settings.llm_model:
            raise ValueError("strict JSON Schema result is invalid")
        checks["strict_json_schema"] = {
            "status": "passed",
            "input_tokens": structured.usage.prompt_tokens,
            "output_tokens": structured.usage.output_tokens,
            "total_tokens": structured.usage.total_tokens,
            "latency_ms": structured.latency_ms,
        }

        tools = [
            {
                "type": "function",
                "name": "python_ast_check",
                "description": "Validate the selected server-issued Python block.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "code_block_id": {"type": "string", "const": "code_001"}
                    },
                    "required": ["code_block_id"],
                },
                "strict": True,
            }
        ]
        planned = await provider.function_call(
            ProviderRequest(
                task_text=(
                    "Use python_ast_check for server block code_001 before answering:\n"
                    "```python\nprint('synthetic')\n```"
                ),
                stage="tool_planning",
            ),
            tools,
        )
        if len(planned.calls) != 1:
            raise ValueError("function calling did not return exactly one call")
        call = planned.calls[0]
        arguments = json.loads(call.arguments)
        if call.name != "python_ast_check" or arguments != {
            "code_block_id": "code_001"
        }:
            raise ValueError("function call violated the strict allowlist schema")
        if planned.model != settings.llm_model:
            raise ValueError("function call model does not match configured model")
        checks["function_calling"] = {
            "status": "passed",
            "call_count": 1,
            "input_tokens": planned.usage.prompt_tokens,
            "output_tokens": planned.usage.output_tokens,
            "total_tokens": planned.usage.total_tokens,
            "latency_ms": planned.latency_ms,
        }
        checks["actual_usage"] = {"status": "passed", "all_stages_non_fabricated": True}
        report["verified_provider_mode"] = provider.mode.value
        report["verified_model"] = settings.llm_model
    except (ProviderFailure, ValueError, TypeError, json.JSONDecodeError) as exc:
        report["error_code"] = (
            exc.code.value
            if isinstance(exc, ProviderFailure)
            else "PROVIDER_CAPABILITY_FAILED"
        )
        report["failure_stage"] = next(
            (
                name
                for name in ("streaming", "strict_json_schema", "function_calling")
                if name not in checks
            ),
            "usage_or_identity",
        )
        report["failure_type"] = type(exc).__name__
        if isinstance(exc, ProviderFailure):
            report["failure_kind"] = exc.failure_kind
            report["provider_status"] = exc.provider_status
            report["retryable"] = exc.retryable
            report["controlled_failure_detail"] = exc.message
        _emit(report, output)
        return 4
    finally:
        await provider.aclose()

    report["status"] = "passed"
    report["passed_check_count"] = 6
    _emit(report, output)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(_run(arguments.output)))
