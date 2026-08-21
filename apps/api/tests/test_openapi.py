from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.export_openapi import build_document

from memtrace_api.config import Settings
from memtrace_api.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _schema_ref(response: dict[str, object], content_type: str) -> str:
    content = response["content"]
    assert isinstance(content, dict)
    media = content[content_type]
    assert isinstance(media, dict)
    schema = media["schema"]
    assert isinstance(schema, dict)
    ref = schema["$ref"]
    assert isinstance(ref, str)
    return ref


def test_openapi_matches_runtime_error_and_stream_contracts(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            mock_mode=True,
            memtrace_data_dir=tmp_path / "data",
        )
    )
    document = app.openapi()
    paths = document["paths"]

    post_tasks = paths["/api/v1/tasks"]["post"]
    get_task = paths["/api/v1/tasks/{task_id}"]["get"]
    get_events = paths["/api/v1/tasks/{task_id}/events"]["get"]
    for operation in (post_tasks, get_task, get_events):
        assert _schema_ref(operation["responses"]["422"], "application/json").endswith(
            "/ErrorEnvelope"
        )

    stream_content = get_events["responses"]["200"]["content"]
    assert set(stream_content) == {"text/event-stream"}
    assert stream_content["text/event-stream"]["schema"] == {"type": "string"}
    assert _schema_ref(get_events["responses"]["404"], "application/json").endswith(
        "/ErrorEnvelope"
    )
    assert _schema_ref(get_events["responses"]["503"], "application/json").endswith(
        "/ErrorEnvelope"
    )


def test_committed_openapi_is_the_deterministic_generated_document(tmp_path: Path) -> None:
    del tmp_path
    expected = json.dumps(build_document(), ensure_ascii=False, indent=2) + "\n"
    generated = (PROJECT_ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8")
    assert generated == expected


def test_openapi_generation_ignores_environment_overrides(
    monkeypatch,
) -> None:
    baseline = json.dumps(build_document(), ensure_ascii=False, sort_keys=True)
    monkeypatch.setenv("APP_NAME", "")
    monkeypatch.setenv("APP_VERSION", "x" * 100)
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.delitem(sys.modules, "memtrace_api.main", raising=False)
    first = json.dumps(build_document(), ensure_ascii=False, sort_keys=True)
    assert first == baseline
    assert build_document()["info"] == {
        "title": "MemTrace API",
        "version": "0.1.0",
    }
