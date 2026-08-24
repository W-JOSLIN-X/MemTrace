"""Mock verifier using exact-substring algorithm."""

from __future__ import annotations


def verify_exact_substring(output: str, rule: str, avoid: str | None = None) -> tuple[str, str | None]:
    """Return (status, excerpt).

    Priority: avoid > rule.
    """
    if avoid and avoid.strip():
        threshold = max(4, min(12, (len(avoid) + 3) // 4))
        lcs_len = _longest_common_substring_len(output, avoid)
        if lcs_len >= threshold:
            excerpt = _find_excerpt(output, avoid)
            return "violated", excerpt

    if rule and rule.strip():
        threshold = max(4, min(12, (len(rule) + 3) // 4))
        lcs_len = _longest_common_substring_len(output, rule)
        if lcs_len >= threshold:
            excerpt = _find_excerpt(output, rule)
            return "applied", excerpt

    return "not_observable", None


def _longest_common_substring_len(s1: str, s2: str) -> int:
    if not s1 or not s2:
        return 0
    m, n = len(s1), len(s2)
    dp = [0] * (n + 1)
    best = 0
    for i in range(1, m + 1):
        ndp = [0] * (n + 1)
        ci = s1[i - 1]
        for j in range(1, n + 1):
            if ci == s2[j - 1]:
                ndp[j] = dp[j - 1] + 1
                if ndp[j] > best:
                    best = ndp[j]
                    if best >= 12:
                        return best
        dp = ndp
    return best


def _find_excerpt(output: str, target: str) -> str:
    """Find first occurrence of target substring in output, return up to 120 chars."""
    idx = output.find(target[:50])
    if idx == -1:
        return output[:120]
    start = max(0, idx - 30)
    end = min(len(output), idx + len(target) + 30)
    return output[start:end][:120]
