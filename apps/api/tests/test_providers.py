from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIStatusError, APITimeoutError

import memtrace_api.providers as providers_module
from memtrace_api.config import Settings
from memtrace_api.providers import (
    DeepSeekProvider,
    ProviderFailure,
    ProviderMessage,
    ProviderRequest,
)
from memtrace_api.schemas import AsyncErrorCode, PublicPlan


class FakeResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def model_dump(self) -> dict[str, Any]:
        return self._data


class FakeEvent:
    def __init__(self, event_type: str, data: dict[str, Any]) -> None:
        self.type = event_type
        self._data = {"type": event_type, **data}

    def model_dump(self) -> dict[str, Any]:
        return self._data


class FakeStream:
    def __init__(self, events: list[Any]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> FakeStream:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class TransportFailingStream:
    def __init__(self) -> None:
        self.calls = 0

    def __aiter__(self) -> TransportFailingStream:
        return self

    async def __anext__(self) -> Any:
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(type="response.output_text.delta", delta="不得泄露")
        request = httpx.Request("POST", "https://api.deepseek.com/v1/responses")
        raise httpx.RemoteProtocolError("private incomplete body", request=request)


def response_data(
    *,
    output_text: str = '{"answer":"ok"}',
    usage: dict[str, Any] | None = None,
    model: str = "deepseek-v4-flash",
) -> dict[str, Any]:
    return {
        "id": "resp_test",
        "model": model,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": output_text}],
            }
        ],
        "usage": usage
        if usage is not None
        else {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


class FakeResponses:
    def __init__(self) -> None:
        self.kwargs: list[dict[str, Any]] = []
        self.next_result: Any | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs.append(kwargs)
        if self.next_result is not None:
            return self.next_result
        data = response_data()
        return FakeStream(
            [
                SimpleNamespace(
                    type="response.reasoning_summary_text.delta",
                    delta="private-reasoning-must-not-leak",
                ),
                SimpleNamespace(type="response.output_text.delta", delta="最终"),
                SimpleNamespace(
                    type="response.completed",
                    response=FakeResponse(data),
                ),
            ]
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def provider_request() -> ProviderRequest:
    return ProviderRequest(
        task_text="这轮请解释 Python 函数",
        public_plan=PublicPlan(
            id="plan_01J00000000000000000000000",
            goal="解释概念",
            memory_summary="无长期记忆",
            next_action="直接回答",
        ),
        tool_result=None,
        memory_context="<MEMORY><DO>先给结论</DO></MEMORY>",
        conversation=(
            ProviderMessage(role="user", content="我偏好先看结论。"),
            ProviderMessage(role="assistant", content="明白。"),
            ProviderMessage(role="user", content="这轮请解释 Python 函数。"),
        ),
        stage="chat",
    )


def real_settings() -> Settings:
    return Settings(
        _env_file=None,
        mock_mode=False,
        llm_api_key="unit-test-placeholder",
        provider_timeout_seconds=3,
    )


@pytest.mark.asyncio
async def test_deepseek_responses_uses_full_history_and_ignores_reasoning() -> None:
    fake = FakeClient()
    provider = DeepSeekProvider(real_settings(), client=fake)

    items = [item async for item in provider.stream(provider_request())]

    assert "".join(item.delta for item in items) == "最终"
    assert all("private-reasoning" not in item.delta for item in items)
    final = items[-1]
    assert final.usage is not None
    assert final.usage.total_tokens == 18
    assert final.response_id == "resp_test"
    assert final.model == "deepseek-v4-flash"
    assert final.prompt_hash is not None and final.prompt_hash.startswith("sha256:")

    kwargs = fake.responses.kwargs[0]
    assert kwargs["reasoning"] == {"effort": "none"}
    assert kwargs["stream"] is True
    assert kwargs["temperature"] == 0.0
    assert kwargs["input"] == [
        {"role": "user", "content": "我偏好先看结论。"},
        {"role": "assistant", "content": "明白。"},
        {"role": "user", "content": "这轮请解释 Python 函数。"},
    ]
    assert "先给结论" in kwargs["instructions"]
    assert "extra_body" not in kwargs
    assert "previous_response_id" not in kwargs

    await provider.aclose()
    assert fake.closed is True


@pytest.mark.asyncio
async def test_successful_stream_forwards_upstream_token_deltas_immediately() -> None:
    data = response_data(output_text="x" * 200)
    stream = FakeStream(
        [
            *[SimpleNamespace(type="response.output_text.delta", delta="x") for _ in range(200)],
            SimpleNamespace(type="response.completed", response=FakeResponse(data)),
        ]
    )
    fake = SequencedClient([stream])
    provider = DeepSeekProvider(real_settings(), client=fake)

    items = [item async for item in provider.stream(provider_request())]

    deltas = [item.delta for item in items if item.delta]
    assert deltas == ["x"] * 200
    assert items[-1].usage is not None
    assert items[-1].usage.total_tokens == 18
    assert items[-1].first_token_ms is not None


@pytest.mark.asyncio
async def test_structured_output_is_strict_and_locally_validated() -> None:
    fake = FakeClient()
    fake.responses.next_result = FakeResponse(response_data(output_text='{ "answer": "ok" }'))
    provider = DeepSeekProvider(real_settings(), client=fake)
    schema = {
        "name": "answer",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        "strict": False,
    }

    result = await provider.complete_json(provider_request(), schema)

    assert result.parsed == {"answer": "ok"}
    assert result.usage.total_tokens == 18
    assert result.model == "deepseek-v4-flash"
    assert set(fake.responses.kwargs[0]["text"]["format"]) == {"type", "name", "schema"}
    assert (
        "Return data, never the JSON Schema definition itself"
        in fake.responses.kwargs[0]["instructions"]
    )
    assert fake.responses.kwargs[0]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_structured_output_rejects_unknown_fields() -> None:
    fake = FakeClient()
    fake.responses.next_result = FakeResponse(
        response_data(output_text='{"answer":"ok","unknown":true}')
    )
    provider = DeepSeekProvider(real_settings(), client=fake)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }

    with pytest.raises(ProviderFailure, match="Schema"):
        await provider.complete_json(provider_request(), schema)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["stream", "structured"])
async def test_real_provider_rejects_missing_actual_usage(method: str) -> None:
    fake = FakeClient()
    data = response_data(usage={})
    provider = DeepSeekProvider(real_settings(), client=fake)
    if method == "stream":
        fake.responses.next_result = FakeStream(
            [SimpleNamespace(type="response.completed", response=FakeResponse(data))]
        )
        with pytest.raises(ProviderFailure, match="usage"):
            _ = [item async for item in provider.stream(provider_request())]
    else:
        fake.responses.next_result = FakeResponse(data)
        with pytest.raises(ProviderFailure, match="usage"):
            await provider.complete_json(
                provider_request(),
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["answer"],
                    "properties": {"answer": {"type": "string"}},
                },
            )


def test_deepseek_client_has_explicit_timeout_and_no_hidden_sdk_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    fake = FakeClient()

    def fake_constructor(**kwargs: Any) -> FakeClient:
        captured.update(kwargs)
        return fake

    monkeypatch.setattr(providers_module, "AsyncOpenAI", fake_constructor)
    provider = DeepSeekProvider(real_settings())
    assert provider.model == "deepseek-v4-flash"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["timeout"] == 3
    assert captured["max_retries"] == 0


class RaisingResponses:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def create(self, **kwargs: Any) -> None:
        del kwargs
        raise self.error


class RaisingClient:
    def __init__(self, error: Exception) -> None:
        self.responses = RaisingResponses(error)


class SequencedResponses:
    def __init__(self, results: list[Any]) -> None:
        self.results = list(results)
        self.calls = 0

    async def create(self, **kwargs: Any) -> Any:
        del kwargs
        result = self.results[self.calls]
        self.calls += 1
        return result


class SequencedClient:
    def __init__(self, results: list[Any]) -> None:
        self.responses = SequencedResponses(results)


def _status_error(status_code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://api.deepseek.com/responses")
    response = httpx.Response(status_code, request=request, json={"error": "private"})
    return APIStatusError("private upstream body", response=response, body=response.json())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [
        (400, False),
        (401, False),
        (402, False),
        (403, False),
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
    provider = DeepSeekProvider(real_settings(), client=RaisingClient(_status_error(status_code)))
    with pytest.raises(ProviderFailure) as caught:
        _ = [item async for item in provider.stream(provider_request())]
    assert caught.value.code is AsyncErrorCode.PROVIDER_ERROR
    assert caught.value.retryable is retryable
    assert caught.value.provider_status == status_code
    assert "private" not in caught.value.message


@pytest.mark.asyncio
async def test_deepseek_timeout_is_safely_mapped() -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/responses")
    timeout = APITimeoutError(request=request)
    provider = DeepSeekProvider(real_settings(), client=RaisingClient(timeout))
    with pytest.raises(ProviderFailure) as caught:
        _ = [item async for item in provider.stream(provider_request())]
    assert caught.value.code is AsyncErrorCode.PROVIDER_TIMEOUT
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_stream_retries_nested_response_server_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = FakeStream(
        [
            FakeEvent(
                "response.failed",
                {
                    "response": {
                        "status": "failed",
                        "error": {"code": "insufficient_system_resource", "message": "private"},
                    }
                },
            )
        ]
    )
    completed = FakeStream(
        [
            SimpleNamespace(type="response.output_text.delta", delta="完成"),
            SimpleNamespace(
                type="response.completed",
                response=FakeResponse(response_data()),
            ),
        ]
    )
    fake = SequencedClient([failed, completed])
    monkeypatch.setattr(providers_module, "_PROVIDER_RETRY_DELAYS", (0.0,))
    provider = DeepSeekProvider(real_settings(), client=fake)

    items = [item async for item in provider.stream(provider_request())]

    assert "".join(item.delta for item in items) == "完成"
    assert fake.responses.calls == 2


@pytest.mark.asyncio
async def test_stream_does_not_retry_transport_failure_after_visible_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = FakeStream(
        [
            SimpleNamespace(type="response.output_text.delta", delta="重试完成"),
            SimpleNamespace(
                type="response.completed",
                response=FakeResponse(response_data()),
            ),
        ]
    )
    fake = SequencedClient([TransportFailingStream(), completed])
    monkeypatch.setattr(providers_module, "_PROVIDER_RETRY_DELAYS", (0.0,))
    provider = DeepSeekProvider(real_settings(), client=fake)

    received: list[str] = []
    with pytest.raises(ProviderFailure) as caught:
        async for item in provider.stream(provider_request()):
            received.append(item.delta)

    assert received == ["不得泄露"]
    assert caught.value.retryable is True
    assert fake.responses.calls == 1


@pytest.mark.asyncio
async def test_raw_httpx_timeout_is_controlled_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/v1/responses")
    monkeypatch.setattr(providers_module, "_PROVIDER_RETRY_DELAYS", ())
    provider = DeepSeekProvider(
        real_settings(),
        client=RaisingClient(httpx.ReadTimeout("private timeout", request=request)),
    )

    with pytest.raises(ProviderFailure) as caught:
        _ = [item async for item in provider.stream(provider_request())]

    assert caught.value.code is AsyncErrorCode.PROVIDER_TIMEOUT
    assert caught.value.retryable is True
    assert "private" not in caught.value.message


@pytest.mark.asyncio
async def test_stream_does_not_retry_nested_authentication_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = FakeStream(
        [
            FakeEvent(
                "response.failed",
                {
                    "response": {
                        "status": "failed",
                        "error": {"code": "authentication_failed", "message": "private"},
                    }
                },
            )
        ]
    )
    fake = SequencedClient([failed])
    monkeypatch.setattr(providers_module, "_PROVIDER_RETRY_DELAYS", (0.0,))
    provider = DeepSeekProvider(real_settings(), client=fake)

    with pytest.raises(ProviderFailure) as caught:
        _ = [item async for item in provider.stream(provider_request())]

    assert caught.value.retryable is False
    assert fake.responses.calls == 1


@pytest.mark.asyncio
async def test_stream_does_not_retry_max_output_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = FakeStream(
        [
            FakeEvent(
                "response.incomplete",
                {
                    "response": {
                        "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                    }
                },
            )
        ]
    )
    fake = SequencedClient([incomplete])
    monkeypatch.setattr(providers_module, "_PROVIDER_RETRY_DELAYS", (0.0,))
    provider = DeepSeekProvider(real_settings(), client=fake)

    with pytest.raises(ProviderFailure) as caught:
        _ = [item async for item in provider.stream(provider_request())]

    assert caught.value.retryable is False
    assert fake.responses.calls == 1
