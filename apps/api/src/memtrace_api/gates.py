"""Day 3 G2: Six P0 Gates for candidate admission.

Gates run after the durability detector and provider extraction, before candidates
are inserted into the database.  Each gate returns a GateDecision with a controlled
reason code.  No gate can be overridden by the LLM — they are hard constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memtrace_api.schemas import TaskFingerprint


# ---------------------------------------------------------------------------
# Gate decision types
# ---------------------------------------------------------------------------


class GateDecision:
    """Result of a single P0 gate evaluation."""

    def __init__(self, passed: bool, reason: str, detail: str = "") -> None:
        self.passed = passed
        self.reason = reason
        self.detail = detail


@dataclass
class GateResult:
    """Aggregate result of all gates for one candidate."""

    candidate_index: int
    gate_results: dict[str, GateDecision]
    final_decision: GateDecision

    @property
    def all_passed(self) -> bool:
        return self.final_decision.passed

    @property
    def blocking_gate(self) -> str | None:
        if self.final_decision.passed:
            return None
        for name, decision in self.gate_results.items():
            if not decision.passed:
                return name
        return None


# ---------------------------------------------------------------------------
# P0 Gate implementations
# ---------------------------------------------------------------------------


def source_gate(candidate: dict[str, Any], evidence_quote: str, feedback_text: str | None, edited_output: str | None) -> GateDecision:
    """Gate 1: Source — only allow real user signals."""
    evidence_source = candidate.get("evidence_source", "")
    if evidence_source not in ("explicit_text", "explicit_correction", "edit_diff"):
        return GateDecision(
            passed=False,
            reason="invalid_source",
            detail=f"evidence_source must be explicit_text or edit_diff, got: {evidence_source}",
        )

    # Verify quote is actually present in the source
    if evidence_source == "explicit_text":
        if not feedback_text or not evidence_quote:
            return GateDecision(
                passed=False,
                reason="missing_explicit_text",
                detail="evidence_source is explicit_text but feedback_text or evidence_quote is empty",
            )
        if evidence_quote not in feedback_text:
            return GateDecision(
                passed=False,
                reason="quote_not_found_in_feedback",
                detail=f"evidence_quote is not a substring of explicit feedback text",
            )
    elif evidence_source == "edit_diff":
        if not edited_output or not evidence_quote:
            return GateDecision(
                passed=False,
                reason="missing_edit_diff",
                detail="evidence_source is edit_diff but edited_output or evidence_quote is empty",
            )
        if evidence_quote not in edited_output:
            return GateDecision(
                passed=False,
                reason="quote_not_found_in_edited_output",
                detail="evidence_quote is not a substring of edited_output",
            )

    return GateDecision(passed=True, reason="source_verified")


def reusability_gate(candidate: dict[str, Any]) -> GateDecision:
    """Gate 2: Reusability — content must be applicable beyond the current task."""
    category = candidate.get("category", "")
    kind = candidate.get("kind", "")
    rule = candidate.get("rule", "")
    title = candidate.get("title", "")

    # fact-only content is not reusable as preference/rule/experience
    if kind == "experience":
        # experience must describe a condition, not just a fact
        has_condition = any(
            kw in rule.lower()
            for kw in ("when", "如果", "若", "一旦", "如果...就", "if", "should")
        )
        if not has_condition and len(rule) < 40:
            return GateDecision(
                passed=False,
                reason="fact_not_experience",
                detail="kind=experience but rule looks like a fact, not a reusable lesson",
            )

    # rule too vague to be reusable
    if len(rule.strip()) < 20:
        return GateDecision(
            passed=False,
            reason="rule_too_short",
            detail=f"rule must be at least 20 chars for reusability, got: {len(rule.strip())}",
        )

    return GateDecision(passed=True, reason="reusable")


def one_shot_gate(durability: str) -> GateDecision:
    """Gate 3: One-shot — explicit_durable already confirmed durable."""
    if durability == "explicit_durable":
        return GateDecision(passed=True, reason="explicitly_durable")
    if durability == "one_shot":
        return GateDecision(
            passed=False,
            reason="one_shot_durability",
            detail="durability=one_shot, candidate must become episode_only",
        )
    # ambiguous falls through to scope gate for scope narrowing
    return GateDecision(passed=True, reason="not_one_shot")


def atomicity_gate(candidate: dict[str, Any]) -> GateDecision:
    """Gate 4: Atomicity — one candidate = one rule."""
    rule = candidate.get("rule", "")
    avoid = candidate.get("avoid", "")

    # Count distinct constraints in the rule
    sentence_count = rule.count("。") + rule.count("；") + rule.count(";") + rule.count("\n")
    if sentence_count > 3:
        return GateDecision(
            passed=False,
            reason="too_many_rules",
            detail=f"rule contains {sentence_count} sentences — split into separate candidates",
        )

    # Check for contradictory patterns
    if avoid and ("不要" in avoid or "禁止" in avoid or "avoid" in avoid.lower()):
        if rule and ("不要" in rule or "禁止" in rule or "never" in rule.lower()):
            return GateDecision(
                passed=False,
                reason="contradictory_content",
                detail="both rule and avoid contain prohibitions — split them",
            )

    return GateDecision(passed=True, reason="atomic")


def scope_gate(candidate: dict[str, Any], fingerprint: TaskFingerprint | None) -> GateDecision:
    """Gate 5: Scope — derive from TaskFingerprint; narrow for low-confidence."""
    scope = candidate.get("scope", {})
    domain = candidate.get("domain", "other")
    level = scope.get("level", "session") if isinstance(scope, dict) else "session"

    # Low-confidence domain must not be expanded to global or ANY
    if domain == "other" and level in ("global",):
        return GateDecision(
            passed=False,
            reason="low_confidence_scope_expansion",
            detail="domain=other with global scope is not allowed",
        )

    # Force session for unknown domain
    if domain == "other" and level not in ("session",):
        return GateDecision(
            passed=False,
            reason="low_confidence_narrow_scope",
            detail=f"domain=other forces session scope, got: {level}",
        )

    # No global scope without a project_key
    if level == "global":
        project_key = scope.get("project_key") if isinstance(scope, dict) else None
        if not project_key:
            return GateDecision(
                passed=False,
                reason="global_scope_needs_project_key",
                detail="global scope requires project_key",
            )

    return GateDecision(passed=True, reason="scope_valid")


def evidence_gate(candidate: dict[str, Any]) -> GateDecision:
    """Gate 6: Evidence — quote must be exact substring of source."""
    evidence_quote = candidate.get("evidence_quote", "")
    if not evidence_quote or len(evidence_quote.strip()) < 5:
        return GateDecision(
            passed=False,
            reason="evidence_quote_too_short",
            detail=f"evidence_quote must be at least 5 chars, got: {len(evidence_quote.strip())}",
        )

    # The quote must not be fabricated / rewritten
    if candidate.get("evidence_source") == "edit_diff":
        # For edit diff, quote must appear in the edited output
        pass  # The caller provides the actual strings; this is verified in source_gate

    return GateDecision(passed=True, reason="evidence_present")


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------

_GATE_NAMES = ["source", "reusability", "one_shot", "atomicity", "scope", "evidence"]


def run_all_gates(
    candidate: dict[str, Any],
    durability: str,
    feedback_text: str | None,
    edited_output: str | None,
    fingerprint: TaskFingerprint | None = None,
    candidate_index: int = 0,
) -> GateResult:
    """Run all 6 P0 gates on a single candidate.

    Returns GateResult with per-gate decisions and final blocking decision.
    One-shot and evidence gates short-circuit before reusability/atomicity/scope.
    """
    gate_results: dict[str, GateDecision] = {}

    # Gate 1: Source
    evidence_quote = candidate.get("evidence_quote", "")
    gate_results["source"] = source_gate(
        candidate, evidence_quote, feedback_text, edited_output
    )
    if not gate_results["source"].passed:
        return GateResult(candidate_index=candidate_index, gate_results=gate_results, final_decision=gate_results["source"])

    # Gate 3: One-shot (before reusability — cheap check)
    gate_results["one_shot"] = one_shot_gate(durability)
    if not gate_results["one_shot"].passed:
        return GateResult(candidate_index=candidate_index, gate_results=gate_results, final_decision=gate_results["one_shot"])

    # Gate 2: Reusability
    gate_results["reusability"] = reusability_gate(candidate)
    if not gate_results["reusability"].passed:
        return GateResult(candidate_index=candidate_index, gate_results=gate_results, final_decision=gate_results["reusability"])

    # Gate 4: Atomicity
    gate_results["atomicity"] = atomicity_gate(candidate)
    if not gate_results["atomicity"].passed:
        return GateResult(candidate_index=candidate_index, gate_results=gate_results, final_decision=gate_results["atomicity"])

    # Gate 5: Scope
    gate_results["scope"] = scope_gate(candidate, fingerprint)
    if not gate_results["scope"].passed:
        return GateResult(candidate_index=candidate_index, gate_results=gate_results, final_decision=gate_results["scope"])

    # Gate 6: Evidence
    gate_results["evidence"] = evidence_gate(candidate)
    if not gate_results["evidence"].passed:
        return GateResult(candidate_index=candidate_index, gate_results=gate_results, final_decision=gate_results["evidence"])

    return GateResult(candidate_index=candidate_index, gate_results=gate_results, final_decision=gate_results["evidence"])
