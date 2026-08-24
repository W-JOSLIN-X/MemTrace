from __future__ import annotations

import json
from typing import Any

from memtrace_api.config import PROJECT_ROOT
from memtrace_api.logic import analyze_task
from memtrace_api.schemas import TaskCreateRequest, ToolAction

FIXTURE_PATH = PROJECT_ROOT / "fixtures" / "day2" / "g1_classification_feedback_matrix.json"


def test_day2_matrix_contains_24_contract_labeled_entries() -> None:
    fixture = _load_fixture()
    entries = fixture["entries"]
    profiles = fixture["persistent_event_profiles"]

    assert fixture["contract_version"] == "1.1.0"
    assert fixture["classification_source"] == "auto_rule_v1"
    assert len(entries) == 24
    assert len({entry["id"] for entry in entries}) == 24
    assert fixture["feedback_capabilities_after_success"] == [
        "explicit_text",
        "edited_output",
        "rating_1_to_5",
        "accepted",
        "rejected",
    ]

    for entry in entries:
        profile_name = entry["expected_persistent_event_profile"]
        assert profile_name in profiles
        assert profiles[profile_name][-1] == "stream.done"
        assert entry["expected_feedback_available_after"] == "succeeded_only"


def test_day2_matrix_matches_the_deterministic_classifier_and_tool_decision() -> None:
    fixture = _load_fixture()
    default_request = fixture["default_request"]

    for entry in fixture["entries"]:
        request = TaskCreateRequest.model_validate(
            {
                **default_request,
                "task_text": entry["task_text"],
            }
        )
        analysis = analyze_task(request)
        assert analysis.fingerprint.domain.value == entry["expected_domain"], entry["id"]
        assert analysis.fingerprint.task_type.value == entry["expected_task_type"], entry["id"]
        assert analysis.tool_decision.action is ToolAction(entry["expected_tool_action"]), entry[
            "id"
        ]
        assert analysis.fingerprint.classification_source == "auto_rule_v1"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
