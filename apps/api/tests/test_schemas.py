from __future__ import annotations

import pytest
from pydantic import ValidationError

from memtrace_api.schemas import (
    MessageSnapshot,
    ProviderMode,
    RunErrorSnapshot,
    RunStatus,
    TaskSnapshot,
    ToolCallSnapshot,
    utc_now,
)

REQ_ID = "req_01J00000000000000000000001"
TASK_ID = "task_01J00000000000000000000001"
RUN_ID = "run_01J00000000000000000000001"
TOOL_ID = "tool_01J00000000000000000000001"
RESULT_ID = "toolres_01J00000000000000000000001"
MESSAGE_ID = "msg_01J00000000000000000000001"
ERROR_ID = "err_01J00000000000000000000001"


def _tool_values() -> dict[str, object]:
    return {
        "tool_call_id": TOOL_ID,
        "reason": "检测到 Python 代码。",
        "args_summary": {
            "language": "python",
            "code_source": "whole_task_valid_python",
            "code_bytes": 5,
        },
    }


def _snapshot_values() -> dict[str, object]:
    return {
        "request_id": REQ_ID,
        "task_id": TASK_ID,
        "run_id": RUN_ID,
        "run_status": "generating",
        "provider_mode": ProviderMode.MOCK,
        "effective_memory_mode": "on",
        "tool_calls": [],
        "partial_output": "结果",
        "end_offset": 6,
        "updated_at": utc_now(),
    }


@pytest.mark.parametrize(
    "invalid_update",
    [
        {"status": "running", "latency_ms": 1},
        {"status": "running", "result_ref": RESULT_ID},
        {"status": "succeeded", "latency_ms": 1, "result_ref": RESULT_ID},
        {
            "status": "failed",
            "latency_ms": 1,
            "result_ref": RESULT_ID,
            "result": {"valid": True, "syntax_error": None},
        },
    ],
)
def test_tool_snapshot_rejects_status_result_mismatches(
    invalid_update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ToolCallSnapshot.model_validate(_tool_values() | invalid_update)


def test_tool_snapshot_accepts_only_complete_success_and_resultless_failure() -> None:
    succeeded = ToolCallSnapshot.model_validate(
        _tool_values()
        | {
            "status": "succeeded",
            "latency_ms": 1,
            "result_ref": RESULT_ID,
            "result": {"valid": True, "syntax_error": None},
        }
    )
    failed = ToolCallSnapshot.model_validate(_tool_values() | {"status": "failed", "latency_ms": 1})
    assert succeeded.result is not None
    assert failed.result is None
    assert failed.result_ref is None


def test_success_snapshot_requires_matching_final_message() -> None:
    message = MessageSnapshot(id=MESSAGE_ID, content="不同", created_at=utc_now())
    with pytest.raises(ValidationError):
        TaskSnapshot.model_validate(
            _snapshot_values()
            | {
                "run_status": RunStatus.SUCCEEDED,
                "terminal": True,
                "final_message": message,
            }
        )


def test_failed_snapshot_forbids_final_message() -> None:
    message = MessageSnapshot(id=MESSAGE_ID, content="结果", created_at=utc_now())
    error = RunErrorSnapshot(
        error_id=ERROR_ID,
        code="PROVIDER_ERROR",
        message="模型服务失败。",
        retryable=True,
    )
    with pytest.raises(ValidationError):
        TaskSnapshot.model_validate(
            _snapshot_values()
            | {
                "run_status": RunStatus.FAILED,
                "terminal": True,
                "final_message": message,
                "error": error,
            }
        )


def test_nonterminal_snapshot_forbids_terminal_fields() -> None:
    message = MessageSnapshot(id=MESSAGE_ID, content="结果", created_at=utc_now())
    with pytest.raises(ValidationError):
        TaskSnapshot.model_validate(_snapshot_values() | {"final_message": message})
