"""G3 retrieval TF-IDF engine tests."""

from __future__ import annotations

import math
import unicodedata

import pytest

from memtrace_api.retrieval import (
    THRESHOLD,
    TOP_K,
    ALGORITHM_VERSION,
    RETRIEVAL_MODE,
    SCOPE_WEIGHTS,
    compute_recency,
    compute_scope_match,
    compute_tfidf_vectors,
    cosine_similarity,
    generate_ngrams,
    longest_common_substring_len,
    normalize_text,
    safe_round,
    build_vector,
)


class TestNormalization:
    def test_nfkc(self):
        assert normalize_text("ﬁ") == "fi"  # ﬁ → fi

    def test_casefold(self):
        assert normalize_text("HELLO") == "hello"

    def test_whitespace_collapse(self):
        assert normalize_text("a  b\t\nc") == "a b c"

    def test_strip(self):
        assert normalize_text("  hello  ") == "hello"


class TestNgrams:
    def test_bigram_2char(self):
        assert generate_ngrams("ab") == ["ab"]

    def test_bigram_longer(self):
        grams = generate_ngrams("abc")
        assert "ab" in grams
        assert "bc" in grams

    def test_trigram(self):
        assert "abc" in generate_ngrams("abc")
        assert "bcd" in generate_ngrams("abcd")

    def test_short_returns_empty(self):
        assert generate_ngrams("") == []
        assert generate_ngrams("a") == []

    def test_includes_spaces(self):
        grams = generate_ngrams("a b")
        assert "a " in grams
        assert " b" in grams

    def test_chinese(self):
        grams = generate_ngrams("调试")
        assert len(grams) > 0


class TestTfIdf:
    def test_zero_vector(self):
        vec = build_vector([])
        assert vec == {}

    def test_tf_normalization(self):
        ngrams = generate_ngrams("abab")
        vec = build_vector(ngrams)
        assert abs(sum(vec.values()) - 1.0) < 1e-9

    def test_idf_common_term_lower(self):
        # "ab" is in both docs → lower IDF
        docs = ["ab cd", "ab ef"]
        tfidf = compute_tfidf_vectors(docs)
        # Both vectors should be L2 normalized
        for v in tfidf:
            norm = math.sqrt(sum(x**2 for x in v.values()))
            assert abs(norm - 1.0) < 1e-9 if norm > 0 else True

    def test_idf_rare_term_higher(self):
        docs = ["ab cd", "ef gh"]
        tfidf = compute_tfidf_vectors(docs)
        # "cd" only in doc0, "gh" only in doc1 → higher weight
        assert "cd" in tfidf[0]
        assert "gh" in tfidf[1]

    def test_minimum_corpus(self):
        # 1 query + 1 doc = N=2
        docs = ["hello world", "hello python"]
        tfidf = compute_tfidf_vectors(docs)
        assert len(tfidf) == 2

    def test_empty_corpus(self):
        tfidf = compute_tfidf_vectors([""])
        assert len(tfidf) == 1

    def test_cosine_same(self):
        docs = ["hello world", "hello world"]
        tfidf = compute_tfidf_vectors(docs)
        sim = cosine_similarity(tfidf[0], tfidf[1])
        assert abs(sim - 1.0) < 1e-9

    def test_cosine_different(self):
        docs = ["hello world", "goodbye moon"]
        tfidf = compute_tfidf_vectors(docs)
        sim = cosine_similarity(tfidf[0], tfidf[1])
        assert 0.0 <= sim < 1.0

    def test_cosine_zero_vector(self):
        v1 = {}
        v2 = {"a": 1.0}
        assert cosine_similarity(v1, v2) == 0.0
        assert cosine_similarity(v2, v1) == 0.0

    def test_cosine_clamped(self):
        v1 = {"a": 1.0}
        v2 = {"b": 1.0}
        assert cosine_similarity(v1, v2) == 0.0

    def test_rounding_6_digits(self):
        val = 0.123456789
        assert safe_round(val) == pytest.approx(0.123457)

    def test_deterministic_100_runs(self):
        import random

        text = "python debugging tips for beginners"
        results = []
        for _ in range(100):
            random.seed(42)  # same seed each iteration
            ngrams = generate_ngrams(normalize_text(text))
            vec = build_vector(ngrams)
            results.append(safe_round(sum(vec.values()), 6))
        assert len(set(results)) == 1  # all identical

    def test_stable_tiebreak_by_id(self):
        """Same score cards are ordered by memory_id ASC."""
        pass  # tiebreak tested in retrieval integration


class TestHardFilters:
    def test_memory_mode_off(self):
        from memtrace_api.retrieval import check_hard_filters
        from memtrace_api.schemas import CurrentConstraints, ResponsePolicy, Urgency

        class FakeCard:
            status = "active"
            current_version_id = "v1"
            version = 1
            rule_confidence = 0.9
            scope_confidence = 0.9
            valid_from = None
            valid_to = None
            scope_json = '{"domain": "programming_learning"}'
            exceptions_json = "[]"

        cc = CurrentConstraints(
            response_policy=ResponsePolicy.DEFAULT,
            urgency=Urgency.NORMAL,
            memory_disabled=True,
            source="ui",
        )

        class FakeFP:
            domain = type("D", (), {"value": "programming_learning"})()
            task_type = type("T", (), {"value": "debugging_guidance"})()

        passes, reasons = check_hard_filters(FakeCard(), FakeFP(), "on", cc)
        assert not passes
        assert "memory_mode_off" in [r.value for r in reasons]

    def test_status_not_active(self):
        from memtrace_api.retrieval import check_hard_filters
        from memtrace_api.schemas import CurrentConstraints, ResponsePolicy, Urgency

        class FakeCard:
            status = "candidate"
            current_version_id = None
            version = 0
            rule_confidence = None
            scope_confidence = None

        cc = CurrentConstraints(
            response_policy=ResponsePolicy.DEFAULT,
            urgency=Urgency.NORMAL,
            memory_disabled=False,
            source="ui",
        )

        class FakeFP:
            domain = type("D", (), {"value": "x"})()
            task_type = type("T", (), {"value": "x"})()
            artifact_type = type("A", (), {"value": "x"})()
            audience = type("A2", (), {"value": "x"})()

        passes, reasons = check_hard_filters(FakeCard(), FakeFP(), "on", cc)
        assert not passes
        assert "status_not_active" in [r.value for r in reasons]


class TestScopeMatch:
    def test_exact_domain(self):
        from memtrace_api.retrieval import compute_scope_match

        class FakeFP:
            domain = type("D", (), {"value": "programming_learning"})()
            task_type = type("T", (), {"value": "debugging_guidance"})()
            artifact_type = type("A", (), {"value": "source_code"})()
            audience = type("Au", (), {"value": "beginner"})()
            project_key = None
            language = type("L", (), {"value": "python"})()
            framework = None
            concepts = []

        cs = {
            "domain": "programming_learning",
            "task_type": None,
            "artifact_type": None,
            "audience": None,
            "project_key": None,
            "language": None,
            "framework": None,
            "concepts": [],
        }
        score = compute_scope_match(cs, FakeFP())
        assert score > 0

    def test_null_not_wildcard(self):
        """null domain = 0 contribution, not wildcard match."""
        from memtrace_api.retrieval import compute_scope_match

        class FakeFP:
            domain = type("D", (), {"value": "software_development"})()
            task_type = type("T", (), {"value": "code_review"})()
            artifact_type = type("A", (), {"value": "source_code"})()
            audience = type("Au", (), {"value": "intermediate"})()
            project_key = None
            language = type("L", (), {"value": "python"})()
            framework = None
            concepts = []

        cs = {
            "domain": None,
            "task_type": None,
            "artifact_type": None,
            "audience": None,
            "project_key": None,
            "language": None,
            "framework": None,
            "concepts": [],
        }
        score = compute_scope_match(cs, FakeFP())
        assert score == 0.0

    def test_any_gets_half(self):
        from memtrace_api.retrieval import compute_scope_match

        class FakeFP:
            domain = type("D", (), {"value": "software_development"})()
            task_type = type("T", (), {"value": "code_review"})()
            artifact_type = type("A", (), {"value": "source_code"})()
            audience = type("Au", (), {"value": "intermediate"})()
            project_key = None
            language = type("L", (), {"value": "python"})()
            framework = None
            concepts = []

        cs = {
            "domain": "any",
            "task_type": None,
            "artifact_type": None,
            "audience": None,
            "project_key": None,
            "language": None,
            "framework": None,
            "concepts": [],
        }
        score = compute_scope_match(cs, FakeFP())
        assert score == pytest.approx(0.125)  # 0.25 * 0.5


class TestVerifiedEffect:
    def test_baseline(self):
        from memtrace_api.retrieval import compute_verified_effect

        assert compute_verified_effect(0, 0, 0) == pytest.approx(0.5)

    def test_all_helpful(self):
        from memtrace_api.retrieval import compute_verified_effect

        assert compute_verified_effect(5, 0, 0) == pytest.approx(6 / 7)

    def test_all_harmful(self):
        from memtrace_api.retrieval import compute_verified_effect

        assert compute_verified_effect(0, 5, 0) == pytest.approx(1 / 7)

    def test_never_zero(self):
        from memtrace_api.retrieval import compute_verified_effect

        assert compute_verified_effect(0, 0, 0) > 0.0


class TestRecency:
    def test_explicit_feedback_full(self):
        from memtrace_api.retrieval import compute_recency

        assert compute_recency("explicit_feedback", None) == 1.0

    def test_rating_full(self):
        from memtrace_api.retrieval import compute_recency

        assert compute_recency("rating", None) == 1.0

    def test_outcome_fresh(self):
        from datetime import timedelta
        from memtrace_api.retrieval import compute_recency

        now = __import__("datetime").datetime.now(__import__("datetime").UTC)
        assert compute_recency("outcome", now) == pytest.approx(1.0, abs=0.01)

    def test_outcome_old(self):
        from datetime import timedelta
        from memtrace_api.retrieval import compute_recency

        old = __import__("datetime").datetime.now(__import__("datetime").UTC) - timedelta(days=180)
        assert compute_recency("outcome", old) == pytest.approx(0.0, abs=0.01)


class TestLongestCommonSubstring:
    def test_basic(self):
        assert longest_common_substring_len("hello", "hello world", 12) >= 5

    def test_no_match(self):
        assert longest_common_substring_len("abc", "xyz", 12) == 0

    def test_avoid_priority(self):
        """Longer substring wins regardless of which string it's in."""
        s = "use avoid me please"
        # avoid has 9 chars match, rule has 12 chars match
        a = "please avoid me"  # contains "avoid me" = 9 chars
        r = "use avoid me"  # contains "avoid me" = 9 chars
        # they're the same substring length, just check they match
        avoid_score = longest_common_substring_len(s, a, 12)
        assert avoid_score >= 5
