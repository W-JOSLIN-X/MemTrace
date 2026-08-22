from __future__ import annotations

import pytest

from memtrace_api.events import (
    AgentChunkPayload,
    EventType,
    MemoryRetrievalStartedPayload,
    RunCompletedPayload,
    RunMetricsPayload,
    StreamDonePayload,
    TaskStagePayload,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.logic import TaskAnalysis, analyze_task
from memtrace_api.main import _subscription_body
from memtrace_api.schemas import (
    MessageSnapshot,
    ProviderMode,
    RunStatus,
    TaskCreateRequest,
    utc_now,
)
from memtrace_api.store import (
    SubscriptionCapacityError,
    TaskCapacityError,
    TaskStore,
)


def request_model() -> TaskCreateRequest:
    return TaskCreateRequest.model_validate(
        {
            "task_text": "解释递归",
            "memory_mode": "on",
            "current_constraints": {
                "response_policy": "default",
                "urgency": "normal",
                "memory_disabled": False,
                "source": "ui",
            },
        }
    )


def analysis_model() -> TaskAnalysis:
    return analyze_task(request_model())


def make_store(**overrides: int) -> TaskStore:
    values = {
        "max_tasks": 10,
        "max_subscribers_per_task": 3,
        "subscriber_queue_size": 8,
    }
    values.update(overrides)
    return TaskStore(**values)


@pytest.mark.asyncio
async def test_replay_preserves_original_metadata_chunk_interleaving() -> None:
    store = make_store()
    record = await store.create(
        request=request_model(),
        analysis=analysis_model(),
        request_id=new_prefixed_ulid("req"),
        provider_mode=ProviderMode.MOCK,
    )
    await store.emit(
        record,
        EventType.TASK_STAGE,
        TaskStagePayload(stage="generating", progress_label="generating_answer"),
        snapshot_updates={"run_status": RunStatus.GENERATING},
    )
    await store.emit(
        record,
        EventType.AGENT_CHUNK,
        AgentChunkPayload(
            run_id=record.snapshot.run_id,
            chunk_seq=1,
            start_offset=0,
            end_offset=3,
            delta="你",
        ),
        snapshot_updates={"partial_output": "你", "end_offset": 3},
    )
    await store.emit(
        record,
        EventType.RUN_METRICS,
        RunMetricsPayload(
            provider="mock",
            model="fixture-g1",
            provider_mode="mock",
            first_token_ms=1,
            total_ms=2,
            prompt_tokens=1,
            output_tokens=1,
            token_source="mock",
        ),
    )
    subscription = await store.open_subscription(
        record.snapshot.task_id,
        after_event_seq=0,
        after_offset=0,
    )
    assert [entry.event.event_type for entry in subscription.replay] == [
        EventType.TASK_CREATED,
        EventType.TASK_STAGE,
        EventType.AGENT_CHUNK,
        EventType.RUN_METRICS,
    ]
    await subscription.close()


@pytest.mark.asyncio
async def test_transient_memory_event_is_available_to_first_late_subscription() -> None:
    store = make_store()
    record = await store.create(
        request=request_model(),
        analysis=analysis_model(),
        request_id=new_prefixed_ulid("req"),
        provider_mode=ProviderMode.MOCK,
    )
    await store.emit(
        record,
        EventType.MEMORY_RETRIEVAL_STARTED,
        MemoryRetrievalStartedPayload(),
    )
    first = await store.open_subscription(
        record.snapshot.task_id,
        after_event_seq=0,
        after_offset=0,
    )
    assert EventType.MEMORY_RETRIEVAL_STARTED in {entry.event.event_type for entry in first.replay}
    await first.close()
    resumed = await store.open_subscription(
        record.snapshot.task_id,
        after_event_seq=1,
        after_offset=0,
    )
    assert EventType.MEMORY_RETRIEVAL_STARTED in {
        entry.event.event_type for entry in resumed.replay
    }
    await resumed.close()


@pytest.mark.asyncio
async def test_transient_memory_replay_ignores_an_advanced_output_cursor() -> None:
    store = make_store()
    record = await store.create(
        request=request_model(),
        analysis=analysis_model(),
        request_id=new_prefixed_ulid("req"),
        provider_mode=ProviderMode.MOCK,
    )
    await store.emit(
        record,
        EventType.MEMORY_RETRIEVAL_STARTED,
        MemoryRetrievalStartedPayload(),
    )
    output = "已有输出"
    await store.emit(
        record,
        EventType.AGENT_CHUNK,
        AgentChunkPayload(
            run_id=record.snapshot.run_id,
            chunk_seq=1,
            start_offset=0,
            end_offset=len(output.encode("utf-8")),
            delta=output,
        ),
        snapshot_updates={
            "partial_output": output,
            "end_offset": len(output.encode("utf-8")),
        },
    )
    subscription = await store.open_subscription(
        record.snapshot.task_id,
        after_event_seq=1,
        after_offset=record.snapshot.end_offset,
    )
    assert EventType.MEMORY_RETRIEVAL_STARTED in {
        entry.event.event_type for entry in subscription.replay
    }
    assert EventType.AGENT_CHUNK not in {entry.event.event_type for entry in subscription.replay}
    assert EventType.TASK_CREATED not in {entry.event.event_type for entry in subscription.replay}
    await subscription.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", [3, 4])
async def test_overlapping_utf8_chunk_is_replayed_for_boundary_or_split_cursor(cursor: int) -> None:
    store = make_store()
    record = await store.create(
        request=request_model(),
        analysis=analysis_model(),
        request_id=new_prefixed_ulid("req"),
        provider_mode=ProviderMode.MOCK,
    )
    text = "你🙂好"
    await store.emit(
        record,
        EventType.AGENT_CHUNK,
        AgentChunkPayload(
            run_id=record.snapshot.run_id,
            chunk_seq=1,
            start_offset=0,
            end_offset=len(text.encode("utf-8")),
            delta=text,
        ),
        snapshot_updates={"partial_output": text, "end_offset": len(text.encode("utf-8"))},
    )
    subscription = await store.open_subscription(
        record.snapshot.task_id,
        after_event_seq=1,
        after_offset=cursor,
    )
    chunks = [
        entry.event
        for entry in subscription.replay
        if entry.event.event_type is EventType.AGENT_CHUNK
    ]
    assert len(chunks) == 1
    assert chunks[0].data.delta == text
    await subscription.close()


@pytest.mark.asyncio
async def test_chunk_at_exact_end_cursor_is_not_replayed() -> None:
    store = make_store()
    record = await store.create(
        request=request_model(),
        analysis=analysis_model(),
        request_id=new_prefixed_ulid("req"),
        provider_mode=ProviderMode.MOCK,
    )
    await store.emit(
        record,
        EventType.AGENT_CHUNK,
        AgentChunkPayload(
            run_id=record.snapshot.run_id,
            chunk_seq=1,
            start_offset=0,
            end_offset=3,
            delta="你",
        ),
        snapshot_updates={"partial_output": "你", "end_offset": 3},
    )
    subscription = await store.open_subscription(
        record.snapshot.task_id,
        after_event_seq=1,
        after_offset=3,
    )
    assert all(entry.event.event_type is not EventType.AGENT_CHUNK for entry in subscription.replay)
    await subscription.close()


@pytest.mark.asyncio
async def test_terminal_late_subscription_gets_metadata_through_stream_done() -> None:
    store = make_store()
    record = await store.create(
        request=request_model(),
        analysis=analysis_model(),
        request_id=new_prefixed_ulid("req"),
        provider_mode=ProviderMode.MOCK,
    )
    message = MessageSnapshot(id=new_prefixed_ulid("msg"), content="", created_at=utc_now())
    await store.emit(
        record,
        EventType.RUN_COMPLETED,
        RunCompletedPayload(message_id=message.id, end_offset=0),
        snapshot_updates={
            "run_status": RunStatus.SUCCEEDED,
            "terminal": True,
            "final_message": message,
        },
    )
    await store.emit(
        record,
        EventType.STREAM_DONE,
        StreamDonePayload(status="succeeded"),
    )
    await store.mark_closed(record)
    subscription = await store.open_subscription(
        record.snapshot.task_id,
        after_event_seq=0,
        after_offset=0,
    )
    assert subscription.closed_at_capture is True
    assert subscription.replay[-1].event.event_type is EventType.STREAM_DONE
    snapshot = await store.snapshot(record.snapshot.task_id, request_id=new_prefixed_ulid("req"))
    assert snapshot.terminal is True
    assert snapshot.final_message is not None


@pytest.mark.asyncio
async def test_task_subscriber_and_slow_queue_capacities_are_enforced() -> None:
    store = make_store(max_tasks=1, max_subscribers_per_task=1, subscriber_queue_size=1)
    first = await store.create(
        request=request_model(),
        analysis=analysis_model(),
        request_id=new_prefixed_ulid("req"),
        provider_mode=ProviderMode.MOCK,
    )
    with pytest.raises(TaskCapacityError):
        await store.create(
            request=request_model(),
            analysis=analysis_model(),
            request_id=new_prefixed_ulid("req"),
            provider_mode=ProviderMode.MOCK,
        )
    subscription = await store.open_subscription(
        first.snapshot.task_id,
        after_event_seq=1,
        after_offset=0,
    )
    with pytest.raises(SubscriptionCapacityError):
        await store.open_subscription(
            first.snapshot.task_id,
            after_event_seq=1,
            after_offset=0,
        )
    await store.emit(
        first,
        EventType.TASK_STAGE,
        TaskStagePayload(stage="fingerprinting", progress_label="fingerprinting_task"),
        snapshot_updates={"run_status": RunStatus.FINGERPRINTING},
    )
    await store.emit(
        first,
        EventType.TASK_STAGE,
        TaskStagePayload(stage="retrieving", progress_label="retrieving_memory"),
        snapshot_updates={"run_status": RunStatus.RETRIEVING},
    )
    assert subscription.subscriber is not None
    assert subscription.subscriber.dropped is True
    await subscription.close()


@pytest.mark.asyncio
async def test_idle_subscription_sends_heartbeat_and_unsubscribes_on_close() -> None:
    store = make_store()
    record = await store.create(
        request=request_model(),
        analysis=analysis_model(),
        request_id=new_prefixed_ulid("req"),
        provider_mode=ProviderMode.MOCK,
    )
    subscription = await store.open_subscription(
        record.snapshot.task_id,
        after_event_seq=1,
        after_offset=0,
    )
    assert subscription.subscriber is not None
    subscriber_id = subscription.subscriber.subscriber_id
    body = _subscription_body(subscription, heartbeat_seconds=0.001)
    assert await anext(body) == b": heartbeat\n\n"
    await body.aclose()
    assert subscriber_id not in record.subscribers
