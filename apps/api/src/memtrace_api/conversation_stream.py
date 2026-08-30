"""In-process transient conversation SSE fan-out.

Assistant text deltas deliberately live only in bounded subscriber queues. The
durable event log receives metadata-only turn state transitions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiveConversationEvent:
    event_type: str
    data: dict[str, object]


class ConversationStreamHub:
    def __init__(self, *, queue_size: int = 256, max_subscribers: int = 8) -> None:
        self._queue_size = queue_size
        self._max_subscribers = max_subscribers
        self._subscribers: dict[tuple[str, str], set[asyncio.Queue[LiveConversationEvent]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, owner_id: str, task_id: str) -> asyncio.Queue[LiveConversationEvent]:
        key = (owner_id, task_id)
        queue: asyncio.Queue[LiveConversationEvent] = asyncio.Queue(self._queue_size)
        async with self._lock:
            current = self._subscribers.setdefault(key, set())
            if len(current) >= self._max_subscribers:
                raise RuntimeError("conversation subscriber capacity exceeded")
            current.add(queue)
        return queue

    async def unsubscribe(
        self,
        owner_id: str,
        task_id: str,
        queue: asyncio.Queue[LiveConversationEvent],
    ) -> None:
        key = (owner_id, task_id)
        async with self._lock:
            current = self._subscribers.get(key)
            if current is None:
                return
            current.discard(queue)
            if not current:
                self._subscribers.pop(key, None)

    async def publish(self, owner_id: str, task_id: str, event: LiveConversationEvent) -> None:
        key = (owner_id, task_id)
        async with self._lock:
            queues = tuple(self._subscribers.get(key, ()))
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A slow subscriber must reconnect from the durable cursor. We
                # never block provider generation or retain unbounded text.
                await self.unsubscribe(owner_id, task_id, queue)

    async def publish_delta(
        self,
        *,
        owner_id: str,
        task_id: str,
        run_id: str,
        delta_index: int,
        delta: str,
    ) -> None:
        await self.publish(
            owner_id,
            task_id,
            LiveConversationEvent(
                event_type="assistant.delta",
                data={
                    "run_id": run_id,
                    "delta_index": delta_index,
                    "delta": delta,
                },
            ),
        )

    async def publish_state(
        self,
        *,
        owner_id: str,
        task_id: str,
        event_type: str,
        event_seq: int,
        metadata: dict[str, object],
    ) -> None:
        await self.publish(
            owner_id,
            task_id,
            LiveConversationEvent(
                event_type=event_type,
                data={"event_seq": event_seq, **metadata},
            ),
        )
