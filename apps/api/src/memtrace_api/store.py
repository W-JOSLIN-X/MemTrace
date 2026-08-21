"""Capacity-bounded, process-local task state and ordered replay buffers."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from memtrace_api.events import (
    PERSISTENT_EVENT_TYPES,
    AgentChunkPayload,
    EventEnvelope,
    EventType,
    make_event,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.schemas import (
    ProviderMode,
    RunStatus,
    TaskCreateRequest,
    TaskSnapshot,
    utc_now,
)

MAX_PERSISTENT_EVENTS_PER_TASK = 64
MAX_CHUNK_EVENTS_PER_TASK = 2_048


class TaskMissingError(Exception):
    pass


class TaskCapacityError(Exception):
    pass


class SubscriptionCapacityError(Exception):
    pass


class ReplayCapacityError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ReplayEntry:
    ordinal: int
    event: EventEnvelope


@dataclass(slots=True)
class Subscriber:
    subscriber_id: int
    queue: asyncio.Queue[ReplayEntry]
    dropped: bool = False


@dataclass(slots=True)
class TaskRecord:
    request: TaskCreateRequest
    snapshot: TaskSnapshot
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    replay_entries: list[ReplayEntry] = field(default_factory=list)
    subscribers: dict[int, Subscriber] = field(default_factory=dict)
    next_event_seq: int = 1
    next_ordinal: int = 1
    next_subscriber_id: int = 1
    persistent_count: int = 0
    chunk_count: int = 0
    chunk_buffer_bytes: int = 0
    closed: bool = False
    worker: asyncio.Task[None] | None = None


class Subscription:
    def __init__(
        self,
        *,
        store: TaskStore,
        record: TaskRecord,
        replay: list[ReplayEntry],
        subscriber: Subscriber | None,
        closed_at_capture: bool,
    ) -> None:
        self._store = store
        self._record = record
        self.replay = replay
        self.subscriber = subscriber
        self.closed_at_capture = closed_at_capture

    async def close(self) -> None:
        if self.subscriber is not None:
            await self._store.unsubscribe(self._record, self.subscriber.subscriber_id)


class TaskStore:
    def __init__(
        self,
        *,
        max_tasks: int,
        max_subscribers_per_task: int,
        subscriber_queue_size: int,
    ) -> None:
        self.max_tasks = max_tasks
        self.max_subscribers_per_task = max_subscribers_per_task
        self.subscriber_queue_size = subscriber_queue_size
        self._tasks: OrderedDict[str, TaskRecord] = OrderedDict()
        self._tasks_lock = asyncio.Lock()

    async def create(
        self,
        *,
        request: TaskCreateRequest,
        request_id: str,
        provider_mode: ProviderMode,
    ) -> TaskRecord:
        async with self._tasks_lock:
            if len(self._tasks) >= self.max_tasks:
                terminal_id = next(
                    (task_id for task_id, record in self._tasks.items() if record.closed),
                    None,
                )
                if terminal_id is None:
                    raise TaskCapacityError
                self._tasks.pop(terminal_id)

            task_id = new_prefixed_ulid("task")
            run_id = new_prefixed_ulid("run")
            snapshot = TaskSnapshot(
                request_id=request_id,
                task_id=task_id,
                run_id=run_id,
                run_status=RunStatus.QUEUED,
                provider_mode=provider_mode,
                effective_memory_mode=request.effective_memory_mode,
                tool_calls=[],
                updated_at=utc_now(),
            )
            record = TaskRecord(request=request, snapshot=snapshot)
            self._tasks[task_id] = record

        await self.emit(
            record,
            EventType.TASK_CREATED,
            {"task_status": "active", "run_status": "queued"},
        )
        return record

    async def get(self, task_id: str) -> TaskRecord:
        async with self._tasks_lock:
            record = self._tasks.get(task_id)
        if record is None:
            raise TaskMissingError
        return record

    async def snapshot(self, task_id: str, *, request_id: str) -> TaskSnapshot:
        record = await self.get(task_id)
        async with record.lock:
            values = record.snapshot.model_dump(mode="python")
            values["request_id"] = request_id
            return TaskSnapshot.model_validate(values)

    async def emit(
        self,
        record: TaskRecord,
        event_type: EventType,
        data: Any,
        *,
        snapshot_updates: dict[str, Any] | None = None,
    ) -> EventEnvelope:
        async with record.lock:
            persistent = event_type in PERSISTENT_EVENT_TYPES
            if persistent and record.persistent_count >= MAX_PERSISTENT_EVENTS_PER_TASK:
                raise ReplayCapacityError("persistent replay capacity reached")
            if (
                event_type is EventType.AGENT_CHUNK
                and record.chunk_count >= MAX_CHUNK_EVENTS_PER_TASK
            ):
                raise ReplayCapacityError("chunk replay capacity reached")

            event_seq = record.next_event_seq if persistent else None
            event = make_event(
                event_type=event_type,
                event_seq=event_seq,
                task_id=record.snapshot.task_id,
                run_id=record.snapshot.run_id,
                data=data,
            )

            updates = dict(snapshot_updates or {})
            updates["updated_at"] = utc_now()
            if persistent:
                updates["last_persistent_event_seq"] = event_seq
            snapshot_values = record.snapshot.model_dump(mode="python")
            snapshot_values.update(updates)
            record.snapshot = TaskSnapshot.model_validate(snapshot_values)

            ordinal = record.next_ordinal
            record.next_ordinal += 1
            if persistent:
                record.next_event_seq += 1
                record.persistent_count += 1

            entry = ReplayEntry(ordinal=ordinal, event=event)
            if persistent or event_type in {
                EventType.MEMORY_RETRIEVAL_STARTED,
                EventType.AGENT_CHUNK,
            }:
                record.replay_entries.append(entry)
            if event_type is EventType.AGENT_CHUNK:
                payload = event.data
                assert isinstance(payload, AgentChunkPayload)
                record.chunk_count += 1
                record.chunk_buffer_bytes += len(payload.delta.encode("utf-8"))

            dropped_ids: list[int] = []
            for subscriber_id, subscriber in record.subscribers.items():
                try:
                    subscriber.queue.put_nowait(entry)
                except asyncio.QueueFull:
                    subscriber.dropped = True
                    dropped_ids.append(subscriber_id)
            for subscriber_id in dropped_ids:
                record.subscribers.pop(subscriber_id, None)
            return event

    async def mark_closed(self, record: TaskRecord) -> None:
        async with record.lock:
            record.closed = True
            record.replay_entries = [
                entry
                for entry in record.replay_entries
                if entry.event.event_type is not EventType.AGENT_CHUNK
            ]
            record.chunk_count = 0
            record.chunk_buffer_bytes = 0

    async def open_subscription(
        self,
        task_id: str,
        *,
        after_event_seq: int,
        after_offset: int,
    ) -> Subscription:
        record = await self.get(task_id)
        async with record.lock:
            high_water = record.next_ordinal - 1
            replay = [
                entry
                for entry in record.replay_entries
                if entry.ordinal <= high_water
                and _entry_is_after(
                    entry.event,
                    after_event_seq=after_event_seq,
                    after_offset=after_offset,
                )
            ]
            subscriber: Subscriber | None = None
            if not record.closed:
                if len(record.subscribers) >= self.max_subscribers_per_task:
                    raise SubscriptionCapacityError
                subscriber = Subscriber(
                    subscriber_id=record.next_subscriber_id,
                    queue=asyncio.Queue(maxsize=self.subscriber_queue_size),
                )
                record.next_subscriber_id += 1
                record.subscribers[subscriber.subscriber_id] = subscriber
            return Subscription(
                store=self,
                record=record,
                replay=replay,
                subscriber=subscriber,
                closed_at_capture=record.closed,
            )

    async def unsubscribe(self, record: TaskRecord, subscriber_id: int) -> None:
        async with record.lock:
            record.subscribers.pop(subscriber_id, None)

    async def cancel_workers(self) -> None:
        async with self._tasks_lock:
            workers = [record.worker for record in self._tasks.values() if record.worker]
        for worker in workers:
            if worker is not None and not worker.done():
                worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)


def _entry_is_after(
    event: EventEnvelope,
    *,
    after_event_seq: int,
    after_offset: int,
) -> bool:
    if event.event_seq is not None:
        return event.event_seq > after_event_seq
    if isinstance(event.data, AgentChunkPayload):
        # Replay an overlapping chunk in full. The client can safely keep the
        # suffix when the cursor is on a UTF-8 boundary, or fall back to the
        # authoritative snapshot when an arbitrary cursor splits a code point.
        return event.data.end_offset > after_offset
    if event.event_type is EventType.MEMORY_RETRIEVAL_STARTED:
        # This idempotent transient event has no independent cursor. Replaying
        # it on every subscription is the only way to avoid losing it when a
        # disconnect happens between adjacent persistent metadata events.
        return True
    return False
