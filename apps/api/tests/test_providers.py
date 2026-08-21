from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIStatusError, APITimeoutError

import memtrace_api.providers as providers_module
from memtrace_api.config import Settings
from memtrace_api.providers import DeepSeekProvider, ProviderFailure, ProviderRequest
from memtrace_api.schemas import AsyncErrorCode, PublicPlan


@dataclass
class FakeUsage:
    prompt_tokens: int
    completion_tokens: int


class FakeStream:
    def __init__(self) -> None:
        self._chunks = iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="最终",
                                reasoning_content="private-reasoning-must-not-leak",
                            )
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(choices=[], usage=FakeUsage(11, 7)),
            ]
        )

    def __aiter__(self) -> FakeStream:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> FakeStream:
        self.kwargs = kwargs
        return FakeStream()


class FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions())
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def provider_request() -> ProviderRequest:
    return ProviderRequest(
        task_text="解释 Python 函数",
        public_plan=PublicPlan(
            id="plan_01J00000000000000000000000",
            goal="解释概念",
            memory_summary="无长期记忆",
            next_action="直接回答",
        ),
        tool_result=None,
    )


@pytest.mark.asyncio
async def test_deepseek_disables_thinking_requests_usage_and_ignores_reasoning() -> None:
    fake = FakeClient()
    settings = Settings(
        _env_file=None,
        mock_mode=False,
        llm_api_key="unit-test-key",
        provider_timeout_seconds=3,
    )
    provider = DeepSeekProvider(settings, client=fake)
    items = [item async for item in provider.stream(provider_request())]
    assert "".join(item.delta for item in items) == "最终"
    assert all("private-reasoning" not in item.delta for item in items)
    assert items[-1].usage is not None
    assert fake.chat.completions.kwargs is not None
    assert fake.chat.completions.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert fake.chat.completions.kwargs["stream_options"] == {"include_usage": True}
    assert fake.chat.completions.kwargs["stream"] is True
    await provider.aclose()
    assert fake.closed is True


def test_deepseek_client_has_explicit_timeout_and_no_hidden_sdk_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    fake = FakeClient()

    def fake_constructor(**kwargs: Any) -> FakeClient:
        captured.update(kwargs)
        return fake

    monkeypatch.setattr(providers_module, "AsyncOpenAI", fake_constructor)
    settings = Settings(
        _env_file=None,
        mock_mode=False,
        llm_api_key="unit-test-placeholder",
        llm_base_url="https://api.deepseek.com",
        provider_timeout_seconds=7,
    )
    provider = DeepSeekProvider(settings)
    assert provider.model == "deepseek-v4-flash"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["timeout"] == 7
    assert captured["max_retries"] == 0


class RaisingCompletions:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def create(self, **kwargs: Any) -> None:
        del kwargs
        raise self.error


class RaisingClient:
    def __init__(self, error: Exception) -> None:
        self.chat = SimpleNamespace(completions=RaisingCompletions(error))


def _status_error(status_code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(status_code, request=request, json={"error": "private"})
    return APIStatusError("private upstream body", response=response, body=response.json())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [
        (400, False),
        (401, False),
        (402, False),
        (408, True),
        (422, False),
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
    ],
)
async def test_deepseek_status_errors_are_safely_mapped(
    status_code: int,
    retryable: bool,
) -> None:
    settings = Settings(_env_file=None, mock_mode=False, llm_api_key="unit-test-placeholder")
    provider = DeepSeekProvider(settings, client=RaisingClient(_status_error(status_code)))
    with pytest.raises(ProviderFailure) as caught:
        _ = [item async for item in provider.stream(provider_request())]
    assert caught.value.code is AsyncErrorCode.PROVIDER_ERROR
    assert caught.value.retryable is retryable
    assert caught.value.provider_status == status_code
    assert "private" not in caught.value.message


@pytest.mark.asyncio
async def test_deepseek_timeout_is_safely_mapped() -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    timeout = APITimeoutError(request=request)
    settings = Settings(_env_file=None, mock_mode=False, llm_api_key="unit-test-placeholder")
    provider = DeepSeekProvider(settings, client=RaisingClient(timeout))
    with pytest.raises(ProviderFailure) as caught:
        _ = [item async for item in provider.stream(provider_request())]
    assert caught.value.code is AsyncErrorCode.PROVIDER_TIMEOUT
    assert caught.value.retryable is True
