from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from memtrace_api.config import Settings
from memtrace_api.main import _valid_last_event_id, create_app

TASK_ID = "task_01J00000000000000000000001"


@dataclass
class ClosedSubscription:
    replay: list[Any] = field(default_factory=list)
    subscriber: None = None
    closed_at_capture: bool = True

    async def close(self) -> None:
        return None


@dataclass
class CursorStore:
    calls: list[tuple[int, int]] = field(default_factory=list)

    async def open_subscription(
        self,
        task_id: str,
        *,
        after_event_seq: int,
        after_offset: int,
    ) -> ClosedSubscription:
        assert task_id == TASK_ID
        self.calls.append((after_event_seq, after_offset))
        return ClosedSubscription()

    async def cancel_workers(self) -> None:
        return None


def _client(tmp_path: Path, store: CursorStore) -> TestClient:
    settings = Settings(
        _env_file=None,
        app_env="test",
        mock_mode=True,
        memtrace_data_dir=tmp_path / "data",
    )
    return TestClient(create_app(settings, store=store))


def test_valid_last_event_id_and_explicit_query_precedence(tmp_path: Path) -> None:
    store = CursorStore()
    with _client(tmp_path, store) as client:
        from_header = client.get(
            f"/api/v1/tasks/{TASK_ID}/events?after_offset=12",
            headers={"Last-Event-ID": "7"},
        )
        explicit_query = client.get(
            f"/api/v1/tasks/{TASK_ID}/events?after_event_seq=3&after_offset=9",
            headers={"Last-Event-ID": "7"},
        )
    assert from_header.status_code == 200
    assert explicit_query.status_code == 200
    assert store.calls == [(7, 12), (3, 9)]


def test_invalid_or_pathological_last_event_id_safely_falls_back_to_zero(
    tmp_path: Path,
) -> None:
    store = CursorStore()
    assert _valid_last_event_id("１２") == 0
    with _client(tmp_path, store) as client:
        huge = client.get(
            f"/api/v1/tasks/{TASK_ID}/events",
            headers={"Last-Event-ID": "9" * 5_000},
        )
    assert huge.status_code == 200
    assert store.calls == [(0, 0)]
