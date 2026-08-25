"""Tests for G3 verifier."""

from __future__ import annotations

from memtrace_api.verifier import verify_exact_substring


class TestVerifier:
    def test_rule_applied(self):
        output = "Always check input validation before processing user data"
        rule = "always check input validation before processing"
        status, excerpt = verify_exact_substring(output, rule)
        assert status == "applied"
        assert excerpt is not None
        assert len(excerpt) <= 120

    def test_avoid_violated(self):
        output = "Please hardcode the API key for simplicity"
        rule = "Never hardcode credentials"
        avoid = "hardcode"
        status, _excerpt = verify_exact_substring(output, rule, avoid)
        assert status == "violated"

    def test_not_observable(self):
        output = "The answer involves 3 steps"
        rule = "always check input validation before processing"
        status, excerpt = verify_exact_substring(output, rule)
        assert status == "not_observable"
        assert excerpt is None

    def test_avoid_priority_over_rule(self):
        """When both avoid and rule match, avoid takes priority."""
        output = "never use hardcoded credentials in production"
        rule = "use credentials securely"
        avoid = "hardcoded"
        status, _ = verify_exact_substring(output, rule, avoid)
        assert status == "violated"

    def test_empty_output(self):
        output = ""
        rule = "some rule"
        status, excerpt = verify_exact_substring(output, rule)
        assert status == "not_observable"
        assert excerpt is None

    def test_empty_rule(self):
        output = "some output"
        rule = ""
        status, _excerpt = verify_exact_substring(output, rule)
        assert status == "not_observable"

    def test_excerpt_max_120(self):
        output = "x" * 200
        rule = "x" * 50
        status, excerpt = verify_exact_substring(output, rule)
        assert status == "applied"
        assert len(excerpt) <= 120

    def test_no_output_no_applied(self):
        """Without output evidence, cannot write applied."""
        # This is an integration test concept - no output = not_observable
        status, _excerpt = verify_exact_substring("", "some rule")
        assert status != "applied"

    def test_threshold_4(self):
        """Short substring (<4 chars) should not match even if found."""
        output = "ab cd ef"
        rule = "ab"
        status, _ = verify_exact_substring(output, rule)
        # "ab" is 2 chars, below threshold of 4
        assert status != "applied"

    def test_exact_substring_chinese(self):
        output = "调试时应先检查边界条件"
        rule = "调试时应先检查边界条件再给出答案"
        status, _excerpt = verify_exact_substring(output, rule)
        assert status == "applied"
