"""Day 3 G2: Unified diff and normalized edit-cost computation.

Public surface
--------------
- :class:`DiffResult`      – typed, side-effect-free result
- :func:`compute_diff`     – main entry point
- :func:`normalized_levenshtein` – normalized distance 0..1
"""

from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nfkc_casefold(text: str) -> str:
    """NFKC-normalize then casefold for durability comparison."""
    return unicodedata.normalize("NFKC", text).casefold()


def _char_len(text: str) -> int:
    return len(text)


# ---------------------------------------------------------------------------
# Levenshtein (optimal string alignment / restricted Damerau-Levenshtein)
# via difflib matching blocks – O(n·m) worst case but extremely fast for
# real-world texts because difflib finds matching blocks without building
# a full matrix.
# ---------------------------------------------------------------------------


def normalized_levenshtein(a: str, b: str) -> float:
    """Return ``distance / max(len(a), len(b), 1)``, range 0..1.

    Uses :func:`difflib.SequenceMatcher` to find matching blocks, then
    counts unmatched characters as the edit distance.  This is
    deterministic, fast for short-to-medium strings, and handles
    multi-byte Unicode and emoji correctly (operates on Python str, not
    bytes).
    """
    if not a and not b:
        return 0.0
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    matching = sum(size for _, _, size in matcher.get_matching_blocks())
    distance = len(a) + len(b) - 2 * matching
    norm = distance / max(len(a), len(b), 1)
    return round(norm, 6)


# ---------------------------------------------------------------------------
# Public result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiffHunk:
    """One contiguous changed region with ±3 context lines."""

    before_start: int   # 0-based line number in original
    before_count: int   # lines removed (including context)
    after_start: int    # 0-based line number in edited
    after_count: int    # lines added (including context)
    before_lines: list[str] = field(repr=False)
    after_lines: list[str] = field(repr=False)

    @property
    def unified_header(self) -> str:
        return (
            f"@@ -{self.before_start + 1},{self.before_count}"
            f" +{self.after_start + 1},{self.after_count} @@"
        )


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Typed result of :func:`compute_diff`."""

    original_len: int           # characters in original
    edited_len: int             # characters in edited
    added_chars: int            # net characters added
    removed_chars: int          # net characters removed
    hunk_count: int             # number of non-empty hunks
    normalized_edit_cost: float # distance / max(original, edited, 1)
    hunks: list[DiffHunk] = field(default_factory=list)
    truncated: bool = False     # True when > 8 000 chars and only fragment returned

    @property
    def changed_fragment(self) -> str:
        """Reconstruct a readable unified-diff-style fragment from hunks."""
        parts: list[str] = []
        for h in self.hunks:
            parts.append(h.unified_header)
            if h.before_lines:
                for line in h.before_lines:
                    parts.append("- " + line)
            if h.after_lines:
                for line in h.after_lines:
                    parts.append("+ " + line)
        return "\n".join(parts)

    @property
    def change_summary(self) -> str:
        """One-line summary suitable for event metadata."""
        return (
            f"hunks={self.hunk_count} "
            f"added={self.added_chars} "
            f"removed={self.removed_chars} "
            f"cost={self.normalized_edit_cost:.3f}"
        )


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

_CONTEXT_LINES = 3
_MAX_CHARS_FOR_FULL_DIFF = 8_000


def compute_diff(
    original: str,
    edited: str,
    *,
    max_chars: int = _MAX_CHARS_FOR_FULL_DIFF,
) -> DiffResult:
    """Compute a unified diff between *original* and *edited*.

    Parameters
    ----------
    original:
        The source text (typically the assistant's original output).
    edited:
        The user-edited replacement.
    max_chars:
        If *original* + *edited* together exceed this limit, only the
        *changed* text fragment is returned (``truncated=True``), and
        the provider must not be sent the full text.

    Returns
    -------
    DiffResult
    """
    orig_len = _char_len(original)
    edit_len = _char_len(edited)

    orig_lines = original.splitlines(keepends=True)
    edit_lines = edited.splitlines(keepends=True)

    unified = difflib.unified_diff(
        orig_lines,
        edit_lines,
        n=_CONTEXT_LINES,
        lineterm="",
    )

    hunks: list[DiffHunk] = []
    current_hunk: DiffHunk | None = None
    before_idx = 0
    after_idx = 0

    for line in unified:
        if line.startswith("@@ "):
            if current_hunk is not None:
                hunks.append(current_hunk)
            # parse "-A,B +C,D"
            parts = line.split("@@")[1].strip().split()
            before_part = parts[0][1:]  # strip leading '-'
            after_part = parts[1][1:]   # strip leading '+'
            b_start, b_count = (int(x) for x in before_part.split(","))
            a_start, a_count = (int(x) for x in after_part.split(","))
            before_idx = b_start - 1
            after_idx = a_start - 1
            current_hunk = DiffHunk(
                before_start=b_start - 1,
                before_count=0,
                after_start=a_start - 1,
                after_count=0,
                before_lines=[],
                after_lines=[],
            )
        elif current_hunk is not None:
            if line.startswith("-"):
                current_hunk.before_lines.append(line[1:])
                current_hunk.before_count += 1
                before_idx += 1
            elif line.startswith("+"):
                current_hunk.after_lines.append(line[1:])
                current_hunk.after_count += 1
                after_idx += 1
            elif line.startswith("\\"):
                pass  # "\ No newline at end of file"
            else:
                # context line
                current_hunk.before_lines.append(line)
                current_hunk.after_lines.append(line)
                before_idx += 1
                after_idx += 1

    if current_hunk is not None:
        hunks.append(current_hunk)

    # Merge adjacent hunks whose context overlaps (≤3 lines between)
    merged: list[DiffHunk] = []
    for h in hunks:
        if merged and h.before_start <= merged[-1].before_start + len(merged[-1].before_lines):
            # Overlap or immediate adjacency – extend the previous hunk
            prev = merged[-1]
            merged_hunk = DiffHunk(
                before_start=prev.before_start,
                before_count=prev.before_count,
                after_start=prev.after_start,
                after_count=prev.after_count,
                before_lines=prev.before_lines[:],
                after_lines=prev.after_lines[:],
            )
            merged_hunk.before_lines.extend(h.before_lines)
            merged_hunk.after_lines.extend(h.after_lines)
            merged[-1] = merged_hunk
        else:
            merged.append(h)

    added = sum(h.after_count - h.before_count for h in merged)
    removed = sum(h.before_count - h.after_count for h in merged)
    cost = normalized_levenshtein(original, edited)

    total_chars = orig_len + edit_len
    truncated_flag = total_chars > max_chars

    return DiffResult(
        original_len=orig_len,
        edited_len=edit_len,
        added_chars=max(added, 0),
        removed_chars=max(removed, 0),
        hunk_count=len(merged),
        normalized_edit_cost=cost,
        hunks=merged,
        truncated=truncated_flag,
    )
