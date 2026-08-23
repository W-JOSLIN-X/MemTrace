"""Structured provider contract tests, including the optional real-client call shape."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from memtrace_api.compiler import (
    DeepSeekStructuredProvider,
    ExtractionSchema,
    MockStructuredProvider,
    ProviderFailure,
)
from memtrace_api.config import Settings


@pytest.mark.asyncio
async def test_mock_provider_uses_exact_user_evidence_deterministically() -> None:
    provider = MockStructuredProvider()
    context = {
        "explicit_text": "以后调试时先给提示再给答案。",
        "edited_output": None,
        "durability": "explicit_durable",
    }
    prompt = "MEMTRACE_CONTEXT_JSON:" + json.dumps(context, ensure_ascii=False)
    first = await provider.complete_json(prompt, ExtractionSchema.model_json_schema())
    second = await provider.complete_json(prompt, ExtractionSchema.model_json_schema())
    assert first == second
    parsed = ExtractionSchema.model_validate(first)
    assert parsed.candidates[0].evidence_quote == context["explicit_text"]
    assert parsed.candidates[0].evidence_source == "explicit_text"


@pytest.mark.asyncio
async def test_mock_provider_covers_empty_invalid_and_provider_failure() -> None:
    provider = MockStructuredProvider()
    empty = await provider.complete_json("", {}, simulation="empty_json")
    assert ExtractionSchema.model_validate(empty).candidates == []

    unknown = await provider.complete_json("", {}, simulation="unknown_fields")
    with pytest.raises(ValueError):
        ExtractionSchema.model_validate(unknown)

    four = await provider.complete_json("", {}, simulation="four_candidates")
    with pytest.raises(ValueError):
        ExtractionSchema.model_validate(four)

    with pytest.raises(ProviderFailure) as caught:
        await provider.complete_json("", {}, simulation="provider_failure")
    assert caught.value.code == "MEMORY_PROVIDER_ERROR"
    assert caught.value.retryable is True


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.completions = _FakeCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.mark.asyncio
async def test_real_provider_uses_json_schema_response_format_with_fake_client() -> None:
    body = {
        "schema_version": "1.0",
        "feedback_summary": "没有可复用内容。",
        "durability": "ambiguous",
        "disposition": "no_memory",
        "candidates": [],
    }
    fake = _FakeClient(json.dumps(body, ensure_ascii=False))
    settings = Settings(
        _env_file=None,
        mock_mode=False,
        llm_api_key="unit-test-placeholder",
    )
    provider = DeepSeekStructuredProvider(settings, client=fake)
    schema = ExtractionSchema.model_json_schema()
    result = await provider.complete_json("prompt", schema)
    assert result == body
    assert fake.completions.kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "memory_extraction",
            "strict": True,
            "schema": schema,
        },
    }


@pytest.mark.asyncio
async def test_real_provider_maps_invalid_json_to_controlled_error() -> None:
    fake = _FakeClient("not-json")
    settings = Settings(
        _env_file=None,
        mock_mode=False,
        llm_api_key="unit-test-placeholder",
    )
    provider = DeepSeekStructuredProvider(settings, client=fake)
    with pytest.raises(ProviderFailure) as caught:
        await provider.complete_json("prompt", ExtractionSchema.model_json_schema())
    assert caught.value.code == "MEMORY_JSON_INVALID"
    assert caught.value.retryable is False
