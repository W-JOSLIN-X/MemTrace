"""Day 3 learning fixture lock: structure, enum consistency, and coverage.

The deterministic durability cross-check lives in ``test_day3_durability.py``;
these tests freeze the fixture's own internal consistency so member B's review
compares expectations, not spelling drift.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from memtrace_api.config import PROJECT_ROOT
from memtrace_api.logic import analyze_task
from memtrace_api.schemas import TaskCreateRequest

FIXTURE_PATH = PROJECT_ROOT / "fixtures" / "day3" / "learning_events.json"
API_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "schemas" / "g0-api.schema.json"

DURABILITY_VALUES = {
    "explicit_durable",
    "one_shot",
    "ambiguous",
    "reinforce_usage_only",
    "harmful_usage_only",
}
CATEGORIES = {"preference", "rule", "experience", "one_shot", "no_memory"}
DISPOSITIONS = {
    "candidate_created",
    "episode_only",
    "reinforce_usage_only",
    "no_memory",
    "failed",
}
KINDS = {
    "preference",
    "constraint",
    "procedure",
    "experience",
    "environment",
    "learning_checkpoint",
}


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_declares_contract_and_review_status(fixture: dict) -> None:
    assert fixture["contract_version"] == "1.2.0"
    assert fixture["review_status"] == "member_b_approved_2026-08-24"
    assert len(fixture["entries"]) >= 24


def test_entry_ids_are_unique(fixture: dict) -> None:
    ids = [entry["id"] for entry in fixture["entries"]]
    assert len(ids) == len(set(ids))


def test_feedback_shapes_validate_against_api_schema(fixture: dict) -> None:
    schema = json.loads(API_SCHEMA_PATH.read_text(encoding="utf-8"))
    resolver = jsonschema.Draft202012Validator(
        {"$ref": "#/$defs/FeedbackCreateRequest", "$defs": schema["$defs"]}
    )
    for entry in fixture["entries"]:
        feedback = {key: value for key, value in entry["feedback"].items() if value is not None}
        assert feedback, entry["id"]
        resolver.validate(feedback)


@pytest.mark.parametrize("index", range(30))
def test_expected_blocks_are_internally_consistent(fixture: dict, index: int) -> None:
    entry = fixture["entries"][index]
    label = entry["id"]
    expected = entry["expected"]

    assert expected["durability"] in DURABILITY_VALUES
    assert expected["category"] in CATEGORIES
    assert expected["disposition"] in DISPOSITIONS
    assert expected["stage_events"] in fixture["stage_paths"]

    count = expected["candidate_count"]
    kinds = expected["candidate_kinds"]
    assert 0 <= count <= 3
    assert len(kinds) == count
    assert set(kinds) <= KINDS
    assert expected["candidate_created_events"] == count
    if expected["save_preselected"]:
        assert count >= 1
        assert expected["durability"] == "explicit_durable"
    if expected["category"] in ("one_shot", "no_memory"):
        assert count == 0
    if expected["job_status"] == "failed":
        assert expected["job_error_code"]
        assert expected["job_failed_event"] is True
    else:
        assert expected["job_error_code"] is None
        assert expected["job_failed_event"] is False

    if entry["feedback"]["edited_output"] is not None:
        assert entry["original_assistant_output"]
        assert entry["original_assistant_output"] != entry["feedback"]["edited_output"]
    else:
        assert entry["original_assistant_output"] is None

    assert label  # sanity: id non-empty


def test_coverage_requires_every_durability_and_candidate_count(fixture: dict) -> None:
    durabilities = {entry["expected"]["durability"] for entry in fixture["entries"]}
    assert durabilities == DURABILITY_VALUES
    counts = {entry["expected"]["candidate_count"] for entry in fixture["entries"]}
    assert {0, 1, 2, 3} <= counts
    assert any(entry["provider_simulation"] == "evidence_not_found" for entry in fixture["entries"])
    assert any(entry["expected"]["job_status"] == "failed" for entry in fixture["entries"])


@pytest.mark.parametrize("index", range(30))
def test_member_b_fingerprint_review_matches_server_derived_result(
    fixture: dict,
    index: int,
) -> None:
    entry = fixture["entries"][index]
    request = TaskCreateRequest.model_validate(
        {
            "task_text": entry["task_text"],
            **fixture["default_request"],
        }
    )
    actual = analyze_task(request).fingerprint
    assert str(actual.domain) == entry["expected_fingerprint"]["domain"], entry["id"]
    assert str(actual.task_type) == entry["expected_fingerprint"]["task_type"], entry["id"]


@pytest.mark.parametrize("index", range(30))
def test_member_b_worker_path_review_matches_current_early_dispositions(
    fixture: dict,
    index: int,
) -> None:
    entry = fixture["entries"][index]
    expected = entry["expected"]
    durability = expected["durability"]
    reason = expected["durability_reason"]

    if expected["job_status"] == "failed":
        assert expected["stage_events"] == "provider_failure_path", entry["id"]
    elif durability == "explicit_durable" or reason == "edit_diff_only":
        assert expected["stage_events"] == "model_path", entry["id"]
    else:
        assert expected["stage_events"] == "skip_model_path", entry["id"]

    if durability == "one_shot":
        assert expected["disposition"] == "episode_only", entry["id"]
    elif durability == "reinforce_usage_only":
        assert expected["disposition"] == "reinforce_usage_only", entry["id"]
    elif durability == "harmful_usage_only":
        assert expected["disposition"] == "no_memory", entry["id"]
    elif durability == "ambiguous" and reason != "edit_diff_only":
        assert expected["disposition"] == "no_memory", entry["id"]
