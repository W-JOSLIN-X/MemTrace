from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from memtrace_api.events import EventType
from memtrace_api.orchestrator import AgentOrchestrator, _consume_task_exception
from memtrace_api.providers import (
    ProviderFailure,
    ProviderRequest,
    ProviderStreamItem,
    ProviderUsage,
)
from memtrace_api.schemas import AsyncErrorCode, ProviderMode, TaskCreateRequest
from memtrace_api.store import TaskStore


def _request() -> TaskCreateRequest:
    return TaskCreateRequest.model_validate(
        {
            "task_text": "解释递归",
            "scenario": "programming_learning",
            "memory_mode": "on",
            "current_constraints": {
                "response_policy": "default",
                "urgency": "normal",
                "memory_disabled": False,
                "source": "ui",
            },
        }
    )


@dataclass
class AttemptProvider:
    attempts: list[list[ProviderStreamItem | ProviderFailure]]
    name: str = "test-provider"
    model: str = "test-model"
    mode: ProviderMode = ProviderMode.MOCK
    calls: int = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamItem]:
        del request
        selected = self.attempts[self.calls]
        self.calls += 1
        for item in selected:
            if isinstance(item, ProviderFailure):
                raise item
            yield item


async def _run(provider: AttemptProvider):
    store = TaskStore(
        max_tasks=2,
        max_subscribers_per_task=2,
        subscriber_queue_size=16,
    )
    record = await store.create(
        request=_request(),
        request_id="req_01J00000000000000000000001",
        provider_mode=ProviderMode.MOCK,
    )
    await AgentOrchestrator(store=store, provider=provider).run(record)
    return record.snapshot


@pytest.mark.asyncio
async def test_empty_provider_stream_retries_once_then_fails() -> None:
    provider = AttemptProvider(attempts=[[], []])
    snapshot = await _run(provider)
    assert provider.calls == 2
    assert snapshot.run_status == "failed"
    assert snapshot.error is not None
    assert snapshot.error.code is AsyncErrorCode.PROVIDER_ERROR
    assert snapshot.partial_output == ""
    assert snapshot.final_message is None


@pytest.mark.asyncio
async def test_usage_only_stream_is_not_treated_as_a_successful_answer() -> None:
    usage = ProviderStreamItem(usage=ProviderUsage(prompt_tokens=8, output_tokens=0))
    provider = AttemptProvider(attempts=[[usage], [usage]])
    snapshot = await _run(provider)
    assert provider.calls == 2
    assert snapshot.run_status == "failed"
    assert snapshot.error is not None
    assert snapshot.error.code is AsyncErrorCode.PROVIDER_ERROR


@pytest.mark.asyncio
async def test_empty_first_attempt_can_retry_to_a_successful_answer() -> None:
    provider = AttemptProvider(
        attempts=[
            [],
            [
                ProviderStreamItem(delta="成功"),
                ProviderStreamItem(usage=ProviderUsage(prompt_tokens=4, output_tokens=2)),
            ],
        ]
    )
    snapshot = await _run(provider)
    assert provider.calls == 2
    assert snapshot.run_status == "succeeded"
    assert snapshot.final_message is not None
    assert snapshot.final_message.content == "成功"


@pytest.mark.asyncio
async def test_failure_after_first_chunk_is_never_silently_retried() -> None:
    failure = ProviderFailure(
        AsyncErrorCode.PROVIDER_ERROR,
        "上游流中断。",
        retryable=True,
    )
    provider = AttemptProvider(
        attempts=[
            [ProviderStreamItem(delta="部分"), failure],
            [ProviderStreamItem(delta="不应出现")],
        ]
    )
    snapshot = await _run(provider)
    assert provider.calls == 1
    assert snapshot.run_status == "failed"
    assert snapshot.partial_output == "部分"
    assert snapshot.final_message is None
    assert snapshot.error is not None
    assert snapshot.error.retryable is True


@pytest.mark.asyncio
async def test_invalid_provider_unicode_becomes_a_safe_stream_failure() -> None:
    provider = AttemptProvider(attempts=[[ProviderStreamItem(delta="\ud800")]])
    snapshot = await _run(provider)
    assert provider.calls == 1
    assert snapshot.run_status == "failed"
    assert snapshot.error is not None
    assert snapshot.error.code is AsyncErrorCode.STREAM_INTERRUPTED
    assert snapshot.partial_output == ""


@pytest.mark.asyncio
async def test_output_over_256_kib_is_stopped_and_never_marked_successful() -> None:
    provider = AttemptProvider(
        attempts=[[ProviderStreamItem(delta="x" * 262_145)]],
    )
    snapshot = await _run(provider)
    assert provider.calls == 1
    assert snapshot.run_status == "failed"
    assert snapshot.error is not None
    assert snapshot.error.code is AsyncErrorCode.STREAM_INTERRUPTED
    assert snapshot.end_offset == 262_144
    assert snapshot.final_message is None


@pytest.mark.asyncio
async def test_invalid_provider_metric_labels_cannot_block_terminal_failure() -> None:
    failure = ProviderFailure(
        AsyncErrorCode.PROVIDER_ERROR,
        "上游失败。",
        retryable=False,
    )
    provider = AttemptProvider(attempts=[[failure], [failure]], name="", model="")
    store = TaskStore(
        max_tasks=2,
        max_subscribers_per_task=2,
        subscriber_queue_size=16,
    )
    record = await store.create(
        request=_request(),
        request_id="req_01J00000000000000000000001",
        provider_mode=ProviderMode.MOCK,
    )
    await AgentOrchestrator(store=store, provider=provider).run(record)
    assert record.snapshot.terminal is True
    assert record.snapshot.run_status == "failed"
    assert record.snapshot.error is not None
    assert record.closed is True
    event_types = [entry.event.event_type for entry in record.replay_entries]
    assert EventType.RUN_METRICS in event_types
    assert EventType.RUN_FAILED in event_types
    assert EventType.ERROR in event_types
    assert event_types[-1] is EventType.STREAM_DONE


@pytest.mark.asyncio
async def test_done_callback_logs_only_safe_exception_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fail() -> None:
        raise RuntimeError("private-upstream-diagnostic")

    task = asyncio.create_task(fail())
    await asyncio.gather(task, return_exceptions=True)
    with caplog.at_level(logging.ERROR, logger="memtrace_api.orchestrator"):
        _consume_task_exception(task, task_id="task_safe", run_id="run_safe")
    assert "task_id=task_safe" in caplog.text
    assert "run_id=run_safe" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "private-upstream-diagnostic" not in caplog.text
