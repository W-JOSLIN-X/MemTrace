from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memtrace_api.config import Settings
from memtrace_api.main import create_app


@pytest.fixture
def client_factory(tmp_path: Path) -> Callable[..., TestClient]:
    def build(**overrides: object) -> TestClient:
        values: dict[str, object] = {
            "app_env": "test",
            "mock_mode": True,
            "memtrace_data_dir": tmp_path / "data",
        }
        values.update(overrides)
        settings = Settings(_env_file=None, **values)
        return TestClient(create_app(settings))

    return build
