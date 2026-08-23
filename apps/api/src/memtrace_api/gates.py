"""Deterministic P0 admission gates for Day 3 memory candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memtrace_api.schemas import TaskFingerprint


@dataclass(frozen=True, slots=True)
class GateDecision:
    passed: bool
    reason: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GateResult:
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
        return next(
            (name for name, decision in self.gate_results.items() if not decision.passed),
            None,
        )


def source_gate(
    candidate: dict[str, Any],
    evidence_quote: str,
    feedback_text: str | None,
    edited_output: str | None,
) -> GateDecision:
    source = candidate.get("evidence_source")
    if source == "explicit_text":
        if not feedback_text or not evidence_quote:
            return GateDecision(False, "missing_explicit_text")
        if evidence_quote not in feedback_text:
            return GateDecision(False, "quote_not_found_in_feedback")
    elif source == "edit_diff":
        if not edited_output or not evidence_quote:
            return GateDecision(False, "missing_edit_diff")
        if evidence_quote not in edited_output:
            return GateDecision(False, "quote_not_found_in_edited_output")
    else:
        return GateDecision(False, "invalid_source")
    return GateDecision(True, "source_verified")


def reusability_gate(candidate: dict[str, Any]) -> GateDecision:
    rule = str(candidate.get("rule") or "").strip()
    if len(rule) < 20:
        return GateDecision(False, "rule_too_short")
    if str(candidate.get("kind")) == "experience":
        folded = rule.casefold()
        conditional = any(
            cue in folded for cue in ("如果", "若", "当", "在后续", "when", "if", "whenever")
        )
        if not conditional:
            return GateDecision(False, "experience_without_condition")
    return GateDecision(True, "reusable")


def one_shot_gate(durability: str) -> GateDecision:
    if durability == "one_shot":
        return GateDecision(False, "one_shot_durability")
    return GateDecision(True, "not_one_shot")


def atomicity_gate(candidate: dict[str, Any]) -> GateDecision:
    rule = str(candidate.get("rule") or "")
    separators = sum(rule.count(mark) for mark in ("。", "；", ";", "\n"))
    if separators > 3:
        return GateDecision(False, "too_many_rules")
    return GateDecision(True, "atomic")


def scope_gate(
    candidate: dict[str, Any],
    fingerprint: TaskFingerprint | None,
) -> GateDecision:
    if fingerprint is None:
        return GateDecision(False, "fingerprint_required")
    scope = candidate.get("scope")
    if not isinstance(scope, dict):
        return GateDecision(False, "invalid_scope")

    level = scope.get("level")
    domain = scope.get("domain")
    task_type = scope.get("task_type")
    artifact_type = scope.get("artifact_type")
    audience = scope.get("audience")
    project_key = scope.get("project_key")

    low_confidence = (
        fingerprint.domain.value == "other" or fingerprint.classification_confidence < 0.70
    )
    if low_confidence:
        if level != "session" or domain != "other":
            return GateDecision(False, "low_confidence_scope_too_broad")
        if task_type is not None or project_key is not None:
            return GateDecision(False, "low_confidence_scope_too_broad")
        return GateDecision(True, "scope_narrowed_to_session")

    if domain in {None, "any"} or domain != fingerprint.domain.value:
        return GateDecision(False, "domain_exceeds_fingerprint")
    if level not in {"session", "task_family", "project"}:
        return GateDecision(False, "scope_level_too_broad")
    if level == "task_family" and task_type != fingerprint.task_type.value:
        return GateDecision(False, "task_type_exceeds_fingerprint")
    if level == "project":
        if fingerprint.project_key is None or project_key != fingerprint.project_key:
            return GateDecision(False, "project_scope_not_supported")
    elif project_key is not None:
        return GateDecision(False, "unexpected_project_key")
    if artifact_type is not None and artifact_type != fingerprint.artifact_type.value:
        return GateDecision(False, "artifact_type_exceeds_fingerprint")
    if audience is not None and audience != fingerprint.audience.value:
        return GateDecision(False, "audience_exceeds_fingerprint")
    return GateDecision(True, "scope_supported_by_fingerprint")


def evidence_gate(candidate: dict[str, Any]) -> GateDecision:
    quote = candidate.get("evidence_quote")
    if not isinstance(quote, str) or not quote.strip():
        return GateDecision(False, "evidence_quote_missing")
    if len(quote) > 2_000:
        return GateDecision(False, "evidence_quote_too_long")
    return GateDecision(True, "evidence_present")


def run_all_gates(
    candidate: dict[str, Any],
    durability: str,
    feedback_text: str | None,
    edited_output: str | None,
    fingerprint: TaskFingerprint | None = None,
    candidate_index: int = 0,
) -> GateResult:
    """Run the six gates in their frozen order and stop at the first block."""
    checks = (
        (
            "source",
            lambda: source_gate(
                candidate,
                str(candidate.get("evidence_quote") or ""),
                feedback_text,
                edited_output,
            ),
        ),
        ("reusability", lambda: reusability_gate(candidate)),
        ("one_shot", lambda: one_shot_gate(durability)),
        ("atomicity", lambda: atomicity_gate(candidate)),
        ("scope", lambda: scope_gate(candidate, fingerprint)),
        ("evidence", lambda: evidence_gate(candidate)),
    )
    results: dict[str, GateDecision] = {}
    for name, check in checks:
        decision = check()
        results[name] = decision
        if not decision.passed:
            return GateResult(candidate_index, results, decision)
    return GateResult(candidate_index, results, results["evidence"])
