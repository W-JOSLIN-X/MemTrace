from __future__ import annotations

import json

from memtrace_api.config import PROJECT_ROOT


def _load(relative: str) -> dict:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


def test_day4_retrieval_fixture_is_a_non_executable_30_case_draft() -> None:
    fixture = _load("fixtures/day4/retrieval_events.json")
    assert fixture["review_status"] == "member_b_draft_requires_joint_review"
    assert fixture["executable_in_day3"] is False
    assert len(fixture["entries"]) == 30
    assert len({entry["id"] for entry in fixture["entries"]}) == 30
    assert {entry["expected"] for entry in fixture["entries"]} == {"match", "no_match"}


def test_day5_conflict_fixture_is_a_non_executable_8_case_draft() -> None:
    fixture = _load("fixtures/day5/conflict_events.json")
    assert fixture["review_status"] == "member_b_draft_requires_joint_review"
    assert fixture["executable_in_day3"] is False
    assert len(fixture["entries"]) == 8
    assert len({entry["id"] for entry in fixture["entries"]}) == 8
    assert all(entry["expected_action"] for entry in fixture["entries"])
