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
        "task_text": "print(1)",
        "scenario": "programming_learning",
        "run_status": "generating",
        "provider_mode": ProviderMode.MOCK,
        "effective_memory_mode": "on",
        "tool_calls": [],
        "messages": [],
        "feedback_events": [],
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


def test_feedback_request_validation_rules() -> None:
    from memtrace_api.schemas import (
        DemoAlias,
        DemoSessionCreateRequest,
        DemoSessionResponse,
        FeedbackCreateAccepted,
        FeedbackCreateRequest,
        FeedbackType,
        MemoryJobResponse,
        derive_feedback_type,
    )

    # Valid single text feedback
    req1 = FeedbackCreateRequest(explicit_text="好的建议")
    assert req1.explicit_text == "好的建议"
    assert derive_feedback_type(explicit_text=req1.explicit_text) == FeedbackType.EXPLICIT_TEXT

    # All null rejected
    with pytest.raises(ValidationError):
        FeedbackCreateRequest()

    # Empty or whitespace string rejected
    with pytest.raises(ValidationError):
        FeedbackCreateRequest(explicit_text="   ")
    with pytest.raises(ValidationError):
        FeedbackCreateRequest(edited_output="")

    # Rating validation: must be 1..5 strict int, no bool
    with pytest.raises(ValidationError):
        FeedbackCreateRequest(rating=0)
    with pytest.raises(ValidationError):
        FeedbackCreateRequest(rating=6)
    with pytest.raises(ValidationError):
        FeedbackCreateRequest(rating=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        FeedbackCreateRequest(rating=3.5)  # type: ignore[arg-type]

    req_rating = FeedbackCreateRequest(rating=5)
    assert derive_feedback_type(rating=req_rating.rating) == FeedbackType.RATING

    # Accepted / rejected derive type
    assert derive_feedback_type(accepted=True) == FeedbackType.ACCEPTED
    assert derive_feedback_type(accepted=False) == FeedbackType.REJECTED

    # Composite type when multiple signals
    assert (
        derive_feedback_type(
            explicit_text="修改建议",
            rating=4,
            accepted=True,
        )
        == FeedbackType.COMPOSITE
    )

    # Demo session schemas
    demo_req = DemoSessionCreateRequest(demo_alias=DemoAlias.BLANK_DEMO)
    assert demo_req.demo_alias == "blank_demo"
    with pytest.raises(ValidationError):
        DemoSessionCreateRequest(demo_alias="unknown_alias")  # type: ignore[arg-type]
    demo_resp = DemoSessionResponse(
        request_id=REQ_ID,
        demo_alias=DemoAlias.BLANK_DEMO,
        expires_at=utc_now(),
    )
    assert demo_resp.demo_alias == "blank_demo"

    # Feedback accepted schema
    fb_accepted = FeedbackCreateAccepted(
        request_id=REQ_ID,
        feedback_id="feedback_01J00000000000000000000001",
        memory_job_id="job_01J00000000000000000000001",
        feedback_type=FeedbackType.COMPOSITE,
    )
    assert fb_accepted.job_status == "pending"

    # MemoryJobResponse schema (Day 3 G2 shape)
    job_resp = MemoryJobResponse(
        request_id=REQ_ID,
        memory_job_id="job_01J00000000000000000000001",
        feedback_id="feedback_01J00000000000000000000001",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    assert job_resp.job_type == "extract_feedback"
    assert job_resp.status == "pending"
    assert job_resp.stage.value == "queued"
