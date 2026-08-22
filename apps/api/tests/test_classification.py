from __future__ import annotations

import pytest
from pydantic import ValidationError

from memtrace_api.logic import analyze_task
from memtrace_api.schemas import Domain, TaskCreateRequest


def _request(task_text: str) -> TaskCreateRequest:
    return TaskCreateRequest.model_validate(
        {
            "task_text": task_text,
            "memory_mode": "on",
            "current_constraints": {
                "response_policy": "default",
                "urgency": "normal",
                "memory_disabled": False,
                "source": "ui",
            },
        }
    )


@pytest.mark.parametrize(
    ("task_text", "expected"),
    [
        (
            "我是初学者，请解释这个 Python 报错为什么发生，只给提示不要直接给答案。",
            Domain.PROGRAMMING_LEARNING,
        ),
        (
            "I'm a beginner learning Python. Explain why this traceback happens and "
            "give a hint, not the answer.",
            Domain.PROGRAMMING_LEARNING,
        ),
        (
            "请用教学方式调试这个 Python traceback，解释原因。",
            Domain.PROGRAMMING_LEARNING,
        ),
        ("请重构这个 React 组件并完成代码审查。", Domain.SOFTWARE_DEVELOPMENT),
        ("请配置生产环境依赖并部署 FastAPI 服务。", Domain.SOFTWARE_DEVELOPMENT),
        ("请把这段非技术说明改写得简洁，并总结重点。", Domain.GENERAL_TEXT),
        ("帮我处理一下", Domain.OTHER),
        ("调试并重构这个 bug", Domain.OTHER),
    ],
)
def test_auto_classification_table(task_text: str, expected: Domain) -> None:
    fingerprint = analyze_task(_request(task_text)).fingerprint
    assert fingerprint.domain is expected
    assert fingerprint.classification_source == "auto_rule_v1"
    assert 0 <= fingerprint.classification_confidence <= 1
    assert len(fingerprint.classification_reasons) <= 5
    assert len(fingerprint.classification_reasons) == len(set(fingerprint.classification_reasons))


def test_auto_classification_is_deterministic_except_for_fingerprint_id() -> None:
    request = _request("Please refactor and review this React component for production.")
    first = analyze_task(request).fingerprint.model_dump(exclude={"id"})
    for _ in range(20):
        assert analyze_task(request).fingerprint.model_dump(exclude={"id"}) == first


def test_ambiguous_input_is_low_confidence_other() -> None:
    fingerprint = analyze_task(_request("帮我处理一下")).fingerprint
    assert fingerprint.domain is Domain.OTHER
    assert fingerprint.classification_confidence == 0.2
    assert [reason.value for reason in fingerprint.classification_reasons] == ["ambiguous"]


def test_manual_scenario_is_a_strict_contract_error() -> None:
    values = _request("解释 Python 递归").model_dump(mode="json")
    values["scenario"] = "programming_learning"
    with pytest.raises(ValidationError):
        TaskCreateRequest.model_validate(values)
