"""Fail-fast DeepSeek model-list and minimal Responses API preflight.

The script deliberately prints metadata only. It never prints the API key,
prompt, model output, response body, or raw provider exception.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_SRC = PROJECT_ROOT / "apps" / "api" / "src"
sys.path.insert(0, str(API_SRC))

from memtrace_api.config import Settings
from memtrace_api.providers import (
    DeepSeekProvider,
    ProviderFailure,
    ProviderRequest,
)


async def _run() -> int:
    settings = Settings()
    metadata: dict[str, object] = {
        "has_llm_api_key": settings.has_llm_api_key,
        "provider_mode": settings.provider_mode,
        "base_url": settings.llm_base_url,
        "configured_model": settings.llm_model,
    }
    if settings.mock_mode or not settings.has_llm_api_key:
        metadata["error_code"] = "REAL_PROVIDER_NOT_CONFIGURED"
        print(json.dumps(metadata, separators=(",", ":")))
        return 2

    assert settings.llm_api_key is not None
    headers = {"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"}
    try:
        async with httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/") + "/",
            headers=headers,
            timeout=settings.provider_timeout_seconds,
        ) as client:
            response = await client.get("models")
            metadata["models_status"] = response.status_code
            if response.status_code != 200:
                metadata["error_code"] = "MODEL_LIST_FAILED"
                print(json.dumps(metadata, separators=(",", ":")))
                return 3
            data = response.json()
            model_ids = sorted(
                item["id"]
                for item in data.get("data", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            )
            metadata["available_models"] = model_ids
            metadata["configured_model_available"] = settings.llm_model in model_ids
            if settings.llm_model not in model_ids:
                metadata["error_code"] = "CONFIGURED_MODEL_UNAVAILABLE"
                print(json.dumps(metadata, separators=(",", ":")))
                return 4
    except (httpx.HTTPError, ValueError, TypeError):
        metadata["error_code"] = "MODEL_LIST_TRANSPORT_ERROR"
        print(json.dumps(metadata, separators=(",", ":")))
        return 5

    provider = DeepSeekProvider(settings)
    schema = {
        "name": "preflight",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean", "const": True}},
            "required": ["ok"],
        },
    }
    try:
        output = await provider.complete_json(
            ProviderRequest(
                task_text='Return exactly this JSON value: {"ok":true}',
                output_schema=schema,
                stage="reflection",
            ),
            schema,
        )
    except ProviderFailure as exc:
        metadata["error_code"] = exc.code.value
        metadata["failure_reason"] = exc.message
        metadata["retryable"] = exc.retryable
        metadata["provider_status"] = exc.provider_status
        print(json.dumps(metadata, separators=(",", ":")))
        await provider.aclose()
        return 6
    await provider.aclose()
    metadata.update(
        {
            "responses_status": "ok",
            "response_model": output.model,
            "actual_input_tokens": output.usage.prompt_tokens,
            "actual_output_tokens": output.usage.output_tokens,
            "actual_total_tokens": output.usage.total_tokens,
            "latency_ms": output.latency_ms,
            "prompt_hash_present": output.prompt_hash.startswith("sha256:"),
        }
    )
    print(json.dumps(metadata, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
