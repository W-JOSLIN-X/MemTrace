"""Mock verifier using exact-substring algorithm."""

from __future__ import annotations


def verify_exact_substring(
    output: str, rule: str, avoid: str | None = None
) -> tuple[str, str | None]:
    """Return (status, excerpt).

    Priority: avoid > rule.
    """
    if avoid and avoid.strip():
        threshold = max(4, min(12, (len(avoid) + 3) // 4))
        lcs_len, excerpt = _longest_common_substring(output, avoid)
        if lcs_len >= threshold:
            return "violated", excerpt[:120]

    if rule and rule.strip():
        threshold = max(4, min(12, (len(rule) + 3) // 4))
        lcs_len, excerpt = _longest_common_substring(output, rule)
        if lcs_len >= threshold:
            return "applied", excerpt[:120]

    return "not_observable", None


def _longest_common_substring(s1: str, s2: str) -> tuple[int, str]:
    if not s1 or not s2:
        return 0, ""
    m, n = len(s1), len(s2)
    dp = [0] * (n + 1)
    best = 0
    best_end = 0
    for i in range(1, m + 1):
        ndp = [0] * (n + 1)
        ci = s1[i - 1]
        for j in range(1, n + 1):
            if ci == s2[j - 1]:
                ndp[j] = dp[j - 1] + 1
                if ndp[j] > best:
                    best = ndp[j]
                    best_end = i
        dp = ndp
    return best, s1[best_end - best : best_end]
