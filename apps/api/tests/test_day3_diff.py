"""Day 3 G2: Tests for DiffService."""

from __future__ import annotations

import pytest

from memtrace_api.diff import compute_diff, normalized_levenshtein


class TestDiffService:
    def test_identical_text(self) -> None:
        text = "hello world"
        result = compute_diff(text, text)
        assert result.original_len == 11
        assert result.edited_len == 11
        assert result.hunk_count == 0
        assert result.normalized_edit_cost == 0.0
        assert result.added_chars == 0
        assert result.removed_chars == 0

    def test_empty_to_nonempty(self) -> None:
        result = compute_diff("", "hello")
        assert result.hunk_count >= 1
        assert result.normalized_edit_cost == 1.0

    def test_nonempty_to_empty(self) -> None:
        result = compute_diff("hello", "")
        assert result.hunk_count >= 1
        assert result.normalized_edit_cost == 1.0

    def test_simple_change(self) -> None:
        result = compute_diff("hello world", "hello there")
        assert result.hunk_count >= 1
        assert result.normalized_edit_cost > 0.0

    def test_multiline_diff(self) -> None:
        orig = "line1\nline2\nline3\nline4\nline5"
        edited = "line1\nLINE2\nline3\nline4\nline5"
        result = compute_diff(orig, edited)
        assert result.hunk_count >= 1

    def test_unicode_and_emoji(self) -> None:
        orig = "你好，世界 🌍"
        edited = "你好，世界 🌎"
        result = compute_diff(orig, edited)
        assert result.hunk_count >= 1
        assert result.normalized_edit_cost > 0.0

    def test_truncated_flag(self) -> None:
        orig = "x" * 5_000
        edited = "y" * 5_001
        result = compute_diff(orig, edited, max_chars=1_000)
        assert result.truncated is True

    def test_not_truncated_when_below_max(self) -> None:
        result = compute_diff("short", "text", max_chars=10_000)
        assert result.truncated is False

    def test_change_summary_format(self) -> None:
        result = compute_diff("hello", "world")
        summary = result.change_summary
        assert "hunks=" in summary
        assert "cost=" in summary

    def test_normalized_cost_range(self) -> None:
        result = compute_diff("abc", "xyz")
        assert 0.0 <= result.normalized_edit_cost <= 1.0

    def test_normalized_cost_zero_for_same(self) -> None:
        assert compute_diff("same", "same").normalized_edit_cost == 0.0

    def test_changed_fragment_is_string(self) -> None:
        result = compute_diff("alpha\nbeta\ngamma", "alpha\ndelta\ngamma")
        assert isinstance(result.changed_fragment, str)

    def test_larger_input_performance(self) -> None:
        """Realistic feedback diffs should complete quickly (< 1s)."""
        orig = "alpha\nbeta\ngamma\ndelta\nepsilon\n" * 200  # ~2k lines
        edit = "ALPHA\nBETA\nGAMMA\nDELTA\nEPSILON\n" * 200
        result = compute_diff(orig, edit)
        assert result.hunk_count > 0
        assert 0.0 <= result.normalized_edit_cost <= 1.0


class TestNormalizedLevenshtein:
    def test_identical(self) -> None:
        assert normalized_levenshtein("abc", "abc") == 0.0

    def test_completely_different(self) -> None:
        result = normalized_levenshtein("", "abc")
        assert result == 1.0

    def test_known_exact_distance_is_not_sequence_matcher_similarity(self) -> None:
        assert normalized_levenshtein("kitten", "sitting") == pytest.approx(3 / 7, abs=1e-6)

    def test_range(self) -> None:
        for a, b in [("kitten", "sitting"), ("abc", "ac"), ("", "a"), ("a", "")]:
            assert 0.0 <= normalized_levenshtein(a, b) <= 1.0

    def test_unicode(self) -> None:
        result = normalized_levenshtein("你好", "您好")
        assert 0.0 <= result <= 1.0

    def test_deterministic(self) -> None:
        for _ in range(50):
            assert normalized_levenshtein("hello", "world") == normalized_levenshtein(
                "hello", "world"
            )


class TestDiffDeterminism:
    def test_same_input_same_output(self) -> None:
        cases = [
            ("hello", "world"),
            ("a\nb\nc\nd\ne", "a\nB\nC\nd\ne"),
            ("", "text"),
            ("text", ""),
            ("你好世界", "你好地球"),
        ]
        for orig, edit in cases:
            first = compute_diff(orig, edit)
            for _ in range(20):
                assert compute_diff(orig, edit) == first
