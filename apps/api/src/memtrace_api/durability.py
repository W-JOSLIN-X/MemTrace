"""Day 3 G2: Deterministic durability detector for feedback text.

This is a **pure function** - no I/O, no model call, no randomness.
All input is first NFKC-normalized and casefolded.  The result is used
as a *hard constraint* on the downstream LLM extraction: the model cannot
override an ``one_shot`` or ``explicit_durable`` decision made here.

Reason codes are controlled enum values, not free text.
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum

# ---------------------------------------------------------------------------
# Controlled enums
# ---------------------------------------------------------------------------


class Durability(StrEnum):
    """Five durability outcomes."""

    EXPLICIT_DURABLE = "explicit_durable"
    ONE_SHOT = "one_shot"
    AMBIGUOUS = "ambiguous"
    REINFORCE_USAGE_ONLY = "reinforce_usage_only"
    HARMFUL_USAGE_ONLY = "harmful_usage_only"


class Reason(StrEnum):
    """Controlled reason codes for each durability outcome."""

    # Negative / scoped signals (check FIRST, before durable/one-shot)
    NEGATED_MEMORY_REQUEST = "negated_memory_request"  # memory exclusion
    INTERROGATIVE_CONTEXT = "interrogative_context"  # question context
    QUOTED_OR_REPORTED_SPEECH = "quoted_or_reported_speech"  # reported speech
    MIXED_DURABILITY_SIGNALS = "mixed_durability_signals"  # durable plus one-shot

    # Positive explicit
    DURABLE_MARKER_FOUND = "durable_marker_found"
    ONE_SHOT_MARKER_FOUND = "one_shot_marker_found"

    # Usage-only (no reusable text)
    USAGE_SIGNAL_ONLY_POSITIVE = "usage_signal_only_positive"  # 采纳/好评
    USAGE_SIGNAL_ONLY_NEGATIVE = "usage_signal_only_negative"  # 拒绝/差评
    NEUTRAL_SIGNAL_ONLY = "neutral_signal_only"  # 评分=3/中性

    # Edit diff only
    EDIT_DIFF_ONLY = "edit_diff_only"

    # No clear signal
    NO_CLEAR_SIGNAL = "no_clear_signal"


# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

# Strong long-term markers (Chinese + English)
_DURABLE_MARKERS: set[str] = {
    # Chinese
    "以后",
    "以后都",
    "今后",
    "今后都",
    "以后这类",
    "长期",
    "永久",
    "记住",
    "请记住",
    "记住这个",
    "别忘了",
    "要记住",
    "总是",
    "一直",
    "始终",
    "以后都要",
    "以后请",
    # English
    "always",
    "remember",
    "remember this",
    "from now on",
    "permanently",
    "keep in mind",
    "never forget",
}

# Strong one-shot markers - short phrases (2+ chars) to avoid matching
# common words like "直接" that are often action descriptors, not time-scope.
_ONE_SHOT_MARKERS: set[str] = {
    # Chinese time-scoped phrases
    "这次",
    "本次",
    "当前",
    "暂时",
    "今天",
    "赶时间",
    "仅当前",
    "先给补丁",
    "先给一个补丁",
    "这次先",
    "这次直接",
    "临时",
    "只一次",
    "仅本次",
    "就这次",
    "这次算了",
    "这次就算了",
    # English
    "this time",
    "this one time",
    "one time, skip",
    "just this once",
    "temporary",
    "for now",
    "quick fix",
    "direct fix",
    "patch only",
}

# Negation / exclusion markers targeting memory formation.
# We match short phrases (2+ chars) to avoid false-positives on common Chinese
# action constraints like "永远不要直接修改" (a rule about what to do, not
# what to remember).
_NEGATION_PHRASES: set[str] = {
    "不要记住",
    "不要记",
    "忘了",
    "忘掉",
    "忽略这个",
    "忽略这条",
    "不记得",
    "不用记",
    "don't remember",
    "forget this",
    "forget that",
    "ignore this",
}

# Interrogative
_INTERROGATIVE_MARKERS: set[str] = {
    "？",
    "?",
    "吗",
    "是否",
    "能不能",
    "可不可以",
}

# Quote / reported-speech indicators
# We use longer phrases to avoid false-positives from generic words.
# "老师" alone is too broad (can mean "as a teacher" not "teacher said").
# "和我说" works because it literally means "said to me".
_QUOTE_MARKERS: set[str] = {
    # Chinese specific reporting patterns
    "他和我说",
    "她和我说",
    "和我说",
    "用户说",
    "文档说",
    "写道",
    "写道：",
    "提到",
    "根据",
    "按照",
    "引自",
    "引用",
    # English
    "he said",
    "she said",
    "according to",
    "quoted",
    "mentioned",
    "wrote",
    "said",
    "the docs",
    "the teacher",
}


# ---------------------------------------------------------------------------
# Module-level aliases for concise test assertions
# ---------------------------------------------------------------------------

DURABILITY_EXPLICIT_DURABLE = Durability.EXPLICIT_DURABLE
DURABILITY_ONE_SHOT = Durability.ONE_SHOT
DURABILITY_AMBIGUOUS = Durability.AMBIGUOUS
DURABILITY_REINFORCE_USAGE_ONLY = Durability.REINFORCE_USAGE_ONLY
DURABILITY_HARMFUL_USAGE_ONLY = Durability.HARMFUL_USAGE_ONLY

REASON_DURABLE_MARKER_FOUND = Reason.DURABLE_MARKER_FOUND
REASON_ONE_SHOT_MARKER_FOUND = Reason.ONE_SHOT_MARKER_FOUND
REASON_USAGE_SIGNAL_ONLY_POSITIVE = Reason.USAGE_SIGNAL_ONLY_POSITIVE
REASON_USAGE_SIGNAL_ONLY_NEGATIVE = Reason.USAGE_SIGNAL_ONLY_NEGATIVE
REASON_EDIT_DIFF_ONLY = Reason.EDIT_DIFF_ONLY
REASON_NEGATED_MEMORY_REQUEST = Reason.NEGATED_MEMORY_REQUEST
REASON_INTERROGATIVE_CONTEXT = Reason.INTERROGATIVE_CONTEXT
REASON_QUOTED_OR_REPORTED_SPEECH = Reason.QUOTED_OR_REPORTED_SPEECH
REASON_MIXED_DURABILITY_SIGNALS = Reason.MIXED_DURABILITY_SIGNALS
REASON_NO_CLEAR_SIGNAL = Reason.NO_CLEAR_SIGNAL


# ---------------------------------------------------------------------------
# Core detector
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def detect_durability(
    explicit_text: str | None,
    edited_output: str | None,
    rating: int | None,
    accepted: bool | None,
    *,
    has_editable_diff: bool = False,
) -> tuple[Durability, Reason]:
    """Determine the durability of a feedback signal.

    Parameters
    ----------
    explicit_text:
        Natural-language feedback, already trimmed.
    edited_output:
        User-modified replacement output.
    rating:
        1-5 star rating (``None`` if absent).
    accepted:
        Explicit accept/reject flag.
    has_editable_diff:
        Set ``True`` when *edited_output* was provided and differs
        from the original assistant message.

    Returns
    -------
    (durability, reason)
        Both values are :class:`StrEnum` members that compare equal to
        their plain-string counterparts.
    """
    # ---------- 1. Has any usable content at all? ----------
    has_text = bool(explicit_text and explicit_text.strip())
    has_edit = bool(edited_output and edited_output.strip())

    if not has_text and not has_edit and rating is None and accepted is None:
        return Durability.AMBIGUOUS, Reason.NO_CLEAR_SIGNAL

    # ---------- 2. Normalize explicit text ----------
    working = _normalize(explicit_text) if has_text else ""

    # ---------- 3. Check negative / exclusion first ----------
    # Match negation phrases (2+ chars) so that "不要直接修改" (a concurrent
    # action constraint) is not confused with "不要记住这条" (a memory exclusion).
    if has_text and any(phrase in working for phrase in _NEGATION_PHRASES):
        return Durability.AMBIGUOUS, Reason.NEGATED_MEMORY_REQUEST

    # ---------- 4. Quote / reported speech (check BEFORE interrogative) ----------
    # d3-011 combines reported speech with a question.
    # contains 和我说 (quote) + 吗 (interrogative); fixture expects quoted.
    # When both are present, quote wins because reported-speech is the stronger
    # signal that the user is relaying someone else's preference.
    if has_text and any(phrase in working for phrase in _QUOTE_MARKERS):
        return Durability.AMBIGUOUS, Reason.QUOTED_OR_REPORTED_SPEECH

    # ---------- 5. Interrogative ----------
    if has_text and any(m in working for m in _INTERROGATIVE_MARKERS):
        return Durability.AMBIGUOUS, Reason.INTERROGATIVE_CONTEXT

    # ---------- 6. Check both explicit durable AND one-shot markers ----------
    # Mixed signal check must come BEFORE the individual durable/one-shot checks
    # A phrase combining current-only and future behavior must stay ambiguous.
    durable_hit = has_text and any(m in working for m in _DURABLE_MARKERS)
    one_shot_hit = has_text and any(m in working for m in _ONE_SHOT_MARKERS)

    if durable_hit and one_shot_hit:
        return Durability.AMBIGUOUS, Reason.MIXED_DURABILITY_SIGNALS
    if durable_hit:
        return Durability.EXPLICIT_DURABLE, Reason.DURABLE_MARKER_FOUND
    if one_shot_hit:
        return Durability.ONE_SHOT, Reason.ONE_SHOT_MARKER_FOUND

    # ---------- 7. Edit diff only (no explicit text) ----------
    if has_edit and has_editable_diff and not has_text:
        return Durability.AMBIGUOUS, Reason.EDIT_DIFF_ONLY

    # ---------- 8. Rating / accepted only (no explicit text, no edit) ----------
    if not has_text and not has_edit:
        if accepted is True or (rating is not None and rating >= 4):
            return Durability.REINFORCE_USAGE_ONLY, Reason.USAGE_SIGNAL_ONLY_POSITIVE
        if accepted is False or (rating is not None and rating <= 2):
            return Durability.HARMFUL_USAGE_ONLY, Reason.USAGE_SIGNAL_ONLY_NEGATIVE
        if rating is not None and rating == 3:
            return Durability.AMBIGUOUS, Reason.NEUTRAL_SIGNAL_ONLY
        return Durability.AMBIGUOUS, Reason.NO_CLEAR_SIGNAL

    # ---------- 9. Explicit text +/- edit, no keyword hit ----------
    # When explicit text or edit is present but no keyword matches, the result is
    # ambiguous.  Rating/accepted alone cannot override text signal to force a
    # usage-only or harmful-only result unless there is literally no text at all.
    return Durability.AMBIGUOUS, Reason.NO_CLEAR_SIGNAL
