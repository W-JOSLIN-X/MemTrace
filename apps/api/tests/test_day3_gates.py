"""Independent allow/block coverage for every frozen G2 Admission Gate."""

from __future__ import annotations

from copy import deepcopy

from memtrace_api.gates import (
    atomicity_gate,
    evidence_gate,
    one_shot_gate,
    reusability_gate,
    scope_gate,
    source_gate,
)
from memtrace_api.logic import analyze_task
from memtrace_api.schemas import TaskCreateRequest

FINGERPRINT = analyze_task(
    TaskCreateRequest.model_validate(
        {
            "task_text": "请解释 Python 递归调试时如何检查终止条件。",
            "memory_mode": "on",
            "current_constraints": {
                "response_policy": "guided_hint",
                "urgency": "normal",
                "memory_disabled": False,
                "source": "ui",
            },
        }
    )
).fingerprint

BASE_CANDIDATE = {
    "category": "preference",
    "kind": "preference",
    "title": "递归调试提示偏好",
    "rule": "在后续相似任务中，应先提示检查终止条件，再逐步提供完整答案。",
    "avoid": "",
    "trigger_text": "递归调试任务",
    "scope": {
        "level": "task_family",
        "domain": FINGERPRINT.domain.value,
        "task_type": FINGERPRINT.task_type.value,
        "artifact_type": FINGERPRINT.artifact_type.value,
        "audience": FINGERPRINT.audience.value,
        "project_key": None,
    },
    "exceptions": [],
    "evidence_source": "explicit_text",
    "evidence_quote": "以后先提示检查终止条件",
}


def test_source_gate_allows_exact_user_quote_and_blocks_fabrication() -> None:
    feedback = "以后先提示检查终止条件，再给完整答案。"
    assert source_gate(BASE_CANDIDATE, BASE_CANDIDATE["evidence_quote"], feedback, None).passed
    assert not source_gate(BASE_CANDIDATE, "不存在的证据", feedback, None).passed


def test_reusability_gate_allows_rule_and_blocks_short_fact() -> None:
    assert reusability_gate(BASE_CANDIDATE).passed
    blocked = deepcopy(BASE_CANDIDATE)
    blocked["rule"] = "只是一条事实"
    assert not reusability_gate(blocked).passed


def test_one_shot_gate_allows_durable_and_blocks_one_shot() -> None:
    assert one_shot_gate("explicit_durable").passed
    assert not one_shot_gate("one_shot").passed


def test_atomicity_gate_allows_one_rule_and_blocks_many_rules() -> None:
    assert atomicity_gate(BASE_CANDIDATE).passed
    blocked = deepcopy(BASE_CANDIDATE)
    blocked["rule"] = "先做第一步。再做第二步。然后做第三步。最后做第四步。完成。"
    assert not atomicity_gate(blocked).passed


def test_scope_gate_allows_fingerprint_scope_and_blocks_wildcard() -> None:
    assert scope_gate(BASE_CANDIDATE, FINGERPRINT).passed
    blocked = deepcopy(BASE_CANDIDATE)
    blocked["scope"] = {"level": "global", "domain": "any"}
    assert not scope_gate(blocked, FINGERPRINT).passed
    assert not scope_gate(BASE_CANDIDATE, None).passed


def test_evidence_gate_allows_nonempty_quote_and_blocks_blank() -> None:
    assert evidence_gate(BASE_CANDIDATE).passed
    blocked = deepcopy(BASE_CANDIDATE)
    blocked["evidence_quote"] = "   "
    assert not evidence_gate(blocked).passed
