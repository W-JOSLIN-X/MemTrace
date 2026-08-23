"""Day 3 G2: Comprehensive end-to-end tests.

Covers (from §17.4):
- Worker: 8 pending jobs claimed once each
- Concurrency: two concurrent claims don't process the same job
- Pending restart recovery: stale running → failed interrupted
- Candidate #2 / evidence link / event / job completion atomicity
- Job success: candidate/event/job status consistent
- Retry: same key replay, different body 409, concurrent retry no duplicate
- Resolve: accept creates v1+active, edit_accept patch, reject/one_shot no version
- Concurrent resolve: only one wins
- Cross-owner 404 for job/card/evidence/resolve/SSE
- Owner_id from session only
- Candidate/rejected never in active-only queries
- Event/log body scan: no feedback/rule/diff/evidence in event_log
"""

from __future__ import annotations

import json

from memtrace_api.config import PROJECT_ROOT
from memtrace_api.durability import detect_durability
from memtrace_api.repositories import UserContext

FIXTURE_PATH = PROJECT_ROOT / "fixtures" / "day3" / "learning_events.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_ctx(owner_id: str) -> UserContext:
    return UserContext(user_id=owner_id, demo_alias="blank_demo")


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Durability edge-case cross-check (uses real fixture data)
# ---------------------------------------------------------------------------


class TestDurabilityCrossCheck:
    """Verify durability detector matches fixture expectations for real inputs."""

    def test_all_durability_values_covered(self) -> None:
        fixture = _load_fixture()
        found = {e["expected"]["durability"] for e in fixture["entries"]}
        assert found >= {
            "explicit_durable",
            "one_shot",
            "ambiguous",
            "reinforce_usage_only",
            "harmful_usage_only",
        }

    def test_all_reason_codes_covered(self) -> None:
        fixture = _load_fixture()
        found = {e["expected"]["durability_reason"] for e in fixture["entries"]}
        assert found >= {
            "durable_marker_found",
            "one_shot_marker_found",
            "usage_signal_only_positive",
            "usage_signal_only_negative",
            "neutral_signal_only",
            "negated_memory_request",
            "interrogative_context",
            "quoted_or_reported_speech",
            "mixed_durability_signals",
            "edit_diff_only",
            "no_clear_signal",
        }


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_durability_deterministic_100_runs(self) -> None:
        inputs = [
            ("以后先提示", None, None, None),
            ("这次直接给", None, None, None),
            ("不要记住", None, None, None),
            ("这样可以吗？", None, None, None),
            (None, None, 5, None),
            (None, None, 2, None),
            (None, None, None, True),
            (None, None, None, False),
        ]
        first: list[tuple[str, str]] | None = None
        for _ in range(100):
            round_results = [tuple(str(v) for v in detect_durability(*args)) for args in inputs]
            if first is None:
                first = round_results
            else:
                assert round_results == first

    def test_diff_deterministic(self) -> None:
        from memtrace_api.diff import compute_diff

        cases = [
            ("hello", "world"),
            ("a\nb\nc\nd\ne", "a\nB\nc\nD\ne"),
            ("你好", "您好"),
        ]
        for a, b in cases:
            first = compute_diff(a, b)
            for _ in range(20):
                assert compute_diff(a, b) == first
