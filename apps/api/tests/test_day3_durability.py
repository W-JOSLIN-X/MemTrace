"""Deterministic durability cross-check against ``fixtures/day3/learning_events.json``.

Each entry's ``expected.durability`` and ``expected.durability_reason`` are
verified by running :func:`memtrace_api.durability.detect_durability` on the
fixture's feedback inputs.
"""

from __future__ import annotations

import json

import pytest

from memtrace_api.config import PROJECT_ROOT
from memtrace_api.durability import (
    DURABILITY_AMBIGUOUS,
    DURABILITY_EXPLICIT_DURABLE,
    DURABILITY_HARMFUL_USAGE_ONLY,
    DURABILITY_ONE_SHOT,
    DURABILITY_REINFORCE_USAGE_ONLY,
    REASON_DURABLE_MARKER_FOUND,
    REASON_EDIT_DIFF_ONLY,
    REASON_INTERROGATIVE_CONTEXT,
    REASON_MIXED_DURABILITY_SIGNALS,
    REASON_NEGATED_MEMORY_REQUEST,
    REASON_NO_CLEAR_SIGNAL,
    REASON_ONE_SHOT_MARKER_FOUND,
    REASON_QUOTED_OR_REPORTED_SPEECH,
    REASON_USAGE_SIGNAL_ONLY_NEGATIVE,
    REASON_USAGE_SIGNAL_ONLY_POSITIVE,
    Reason,
    detect_durability,
)

FIXTURE_PATH = PROJECT_ROOT / "fixtures" / "day3" / "learning_events.json"


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Parametrized cross-check against fixture expectations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index", range(30))
def test_durability_matches_fixture(fixture: dict, index: int) -> None:
    entry = fixture["entries"][index]
    fb = entry["feedback"]
    expected = entry["expected"]

    has_edit_diff = fb.get("edited_output") is not None

    durability, reason = detect_durability(
        explicit_text=fb.get("explicit_text"),
        edited_output=fb.get("edited_output"),
        rating=fb.get("rating"),
        accepted=fb.get("accepted"),
        has_editable_diff=has_edit_diff,
    )

    assert str(durability) == expected["durability"], (
        f"{entry['id']}: expected durability {expected['durability']!r}, got {durability!r}"
    )
    assert str(reason) == expected["durability_reason"], (
        f"{entry['id']}: expected reason {expected['durability_reason']!r}, got {reason!r}"
    )


# ---------------------------------------------------------------------------
# Determinism: same input → same output (100 runs)
# ---------------------------------------------------------------------------


def test_durability_is_deterministic() -> None:
    cases = [
        ("以后学习调试先提示", None, None, None),
        ("这次直接给补丁", None, None, None),
        ("可以", None, None, None),
        (None, None, None, None),
        ("always explain first", None, None, None),
    ]
    first_results: list[tuple[str, str]] | None = None
    for _ in range(100):
        round_results = []
        for args in cases:
            d, r = detect_durability(*args[:4], has_editable_diff=False)
            round_results.append((str(d), str(r)))
        if first_results is None:
            first_results = round_results
        else:
            assert round_results == first_results


# ---------------------------------------------------------------------------
# Edge-case unit tests for the detector itself
# ---------------------------------------------------------------------------


class TestDurabilityEdgeCases:
    """Edge cases that the 30-fixture may not cover explicitly."""

    def test_empty_all_fields(self) -> None:
        d, r = detect_durability(None, None, None, None)
        assert d == DURABILITY_AMBIGUOUS
        assert r == REASON_NO_CLEAR_SIGNAL

    def test_explicit_durable_chinese(self) -> None:
        d, r = detect_durability("以后学习调试先提示", None, None, None)
        assert d == DURABILITY_EXPLICIT_DURABLE
        assert r == REASON_DURABLE_MARKER_FOUND

    def test_explicit_durable_english(self) -> None:
        d, r = detect_durability("Always remember: explain first, fix second", None, None, None)
        assert d == DURABILITY_EXPLICIT_DURABLE
        assert r == REASON_DURABLE_MARKER_FOUND

    def test_one_shot_chinese(self) -> None:
        d, r = detect_durability("这次直接给补丁，不要提示", None, None, None)
        assert d == DURABILITY_ONE_SHOT
        assert r == REASON_ONE_SHOT_MARKER_FOUND

    def test_one_shot_english(self) -> None:
        d, r = detect_durability("Just give me the fix this time", None, None, None)
        assert d == DURABILITY_ONE_SHOT
        assert r == REASON_ONE_SHOT_MARKER_FOUND

    def test_negation_is_ambiguous(self) -> None:
        d, r = detect_durability("不要记住这条规则", None, None, None)
        assert d == DURABILITY_AMBIGUOUS
        assert r == REASON_NEGATED_MEMORY_REQUEST

    def test_interrogative_is_ambiguous(self) -> None:
        d, r = detect_durability("以后都要这样吗？", None, None, None)
        assert d == DURABILITY_AMBIGUOUS
        assert r == REASON_INTERROGATIVE_CONTEXT

    def test_quoted_speech_is_ambiguous(self) -> None:
        d, r = detect_durability("同学和我说以后都要先提示", None, None, None)
        assert d == DURABILITY_AMBIGUOUS
        assert r == REASON_QUOTED_OR_REPORTED_SPEECH

    def test_mixed_signal_is_ambiguous(self) -> None:
        d, r = detect_durability("这次先给补丁，以后还是要先提示", None, None, None)
        assert d == DURABILITY_AMBIGUOUS
        assert r == REASON_MIXED_DURABILITY_SIGNALS

    def test_rating_positive_only(self) -> None:
        d, r = detect_durability(None, None, rating=5, accepted=None)
        assert d == DURABILITY_REINFORCE_USAGE_ONLY
        assert r == REASON_USAGE_SIGNAL_ONLY_POSITIVE

    def test_rating_negative_only(self) -> None:
        d, r = detect_durability(None, None, rating=2, accepted=None)
        assert d == DURABILITY_HARMFUL_USAGE_ONLY
        assert r == REASON_USAGE_SIGNAL_ONLY_NEGATIVE

    def test_rating_neutral_only(self) -> None:
        d, r = detect_durability(None, None, rating=3, accepted=None)
        assert d == DURABILITY_AMBIGUOUS
        assert r == Reason.NEUTRAL_SIGNAL_ONLY

    def test_accepted_true(self) -> None:
        d, r = detect_durability(None, None, None, accepted=True)
        assert d == DURABILITY_REINFORCE_USAGE_ONLY
        assert r == REASON_USAGE_SIGNAL_ONLY_POSITIVE

    def test_accepted_false(self) -> None:
        d, r = detect_durability(None, None, None, accepted=False)
        assert d == DURABILITY_HARMFUL_USAGE_ONLY
        assert r == REASON_USAGE_SIGNAL_ONLY_NEGATIVE

    def test_edit_diff_only(self) -> None:
        d, r = detect_durability(
            explicit_text=None,
            edited_output="print('fixed')",
            rating=None,
            accepted=None,
            has_editable_diff=True,
        )
        assert d == DURABILITY_AMBIGUOUS
        assert r == REASON_EDIT_DIFF_ONLY

    def test_unicode_emoji(self) -> None:
        d, r = detect_durability("以后调试先提示 🙏", None, None, None)
        assert d == DURABILITY_EXPLICIT_DURABLE
        assert r == REASON_DURABLE_MARKER_FOUND

    def test_nfkc_normalization(self) -> None:
        # Full-width digits U+FF10-U+FF19 should normalize to ASCII.
        d1, r1 = detect_durability("give me answer１", None, None, None)
        d2, r2 = detect_durability("give me answer1", None, None, None)
        assert d1 == d2
        assert r1 == r2

    def test_whitespace_only_explicit_text(self) -> None:
        d, _r = detect_durability("   ", None, None, None)
        assert d == DURABILITY_AMBIGUOUS

    def test_case_insensitive(self) -> None:
        d1, _r1 = detect_durability("ALWAYS explain first", None, None, None)
        d2, _r2 = detect_durability("always explain first", None, None, None)
        assert d1 == d2

    def test_explicit_text_no_keyword_returns_ambiguous(self) -> None:
        # When explicit text exists but has no keyword marker, the detector
        # returns ambiguous with no-clear-signal reason.
        d, r = detect_durability("这个回答不错", None, None, None)
        assert d == DURABILITY_AMBIGUOUS
        assert r == REASON_NO_CLEAR_SIGNAL

    def test_reason_is_valid_enum(self) -> None:
        for text, rating, accepted in [
            ("以后先提示", None, None),
            ("这次直接给", None, None),
            ("不要记住", None, None),
            ("这样可以吗？", None, None),
            (None, None, True),
            (None, None, False),
            (None, 5, None),
            (None, 2, None),
        ]:
            _, reason = detect_durability(text, None, rating, accepted)
            assert isinstance(reason, Reason), f"Expected Reason, got {type(reason)}"
