"""Build the strict metadata-only Day 7 evaluation artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ArtifactFailure(RuntimeError):
    """Controlled report-validation failure."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactFailure("REPORT_UNREADABLE_OR_INVALID") from exc
    if not isinstance(value, dict):
        raise ArtifactFailure("REPORT_NOT_OBJECT")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _passed_gate(completed: int, expected: int) -> dict[str, object]:
    if completed != expected:
        raise ArtifactFailure("GATE_CARDINALITY_MISMATCH")
    return {
        "status": "passed",
        "completed": completed,
        "expected": expected,
        "failure_code": None,
    }


def _semantic_gate(report: dict[str, Any]) -> dict[str, object]:
    summary = report.get("summary")
    if not isinstance(summary, dict) or summary.get("overall_status") != "passed":
        raise ArtifactFailure("SEMANTIC_REPORT_FAILED")
    if summary.get("semantic_failed") != 0 or summary.get("security_failures") != 0:
        raise ArtifactFailure("SEMANTIC_REPORT_FAILED")
    return _passed_gate(int(summary.get("semantic_passed", -1)), 16)


def _baseline_summary(report: dict[str, Any], name: str) -> dict[str, Any]:
    summaries = report.get("summaries")
    if not isinstance(summaries, list):
        raise ArtifactFailure("BASELINE_SUMMARIES_INVALID")
    matches = [
        item
        for item in summaries
        if isinstance(item, dict) and item.get("baseline") == name
    ]
    if len(matches) != 1:
        raise ArtifactFailure("BASELINE_SUMMARIES_INVALID")
    return matches[0]


def build(args: argparse.Namespace) -> dict[str, Any]:
    preflight = _load(args.provider_preflight)
    validation = _load(args.validation)
    untouched = _load(args.untouched_test)
    memory_ab = _load(args.memory_ab)
    baselines = _load(args.four_baselines)
    calibration = _load(args.calibration)

    if preflight.get("status") != "passed" or preflight.get("passed_check_count") != 6:
        raise ArtifactFailure("PROVIDER_PREFLIGHT_FAILED")
    model = preflight.get("verified_model")
    if not isinstance(model, str) or not model:
        raise ArtifactFailure("MODEL_MISSING")
    for report in (validation, untouched, memory_ab, baselines):
        if report.get("model") != model:
            raise ArtifactFailure("MODEL_MISMATCH")
    if (
        calibration.get("status") != "passed"
        or calibration.get("provider_mode") != "real"
        or calibration.get("model") != model
        or calibration.get("case_count") != 16
        or calibration.get("comparison_count") != 9
        or calibration.get("source_report_sha256") != _canonical_sha256(validation)
    ):
        raise ArtifactFailure("CALIBRATION_REPORT_FAILED")
    selected_config = calibration.get("selected_config")
    if not isinstance(selected_config, dict) or set(selected_config) != {
        "auto_activate_threshold",
        "per_card_token_budget",
        "total_token_budget",
    }:
        raise ArtifactFailure("CALIBRATION_CONFIG_INVALID")
    if (
        selected_config.get("auto_activate_threshold") not in (0.8, 0.85, 0.9)
        or selected_config.get("per_card_token_budget") not in (80, 100, 120)
        or selected_config.get("total_token_budget") not in (240, 300, 360)
    ):
        raise ArtifactFailure("CALIBRATION_CONFIG_INVALID")

    validation_gate = _semantic_gate(validation)
    untouched_gate = _semantic_gate(untouched)
    ab_summary = memory_ab.get("summary")
    if (
        not isinstance(ab_summary, dict)
        or ab_summary.get("overall_status") != "passed"
        or ab_summary.get("ab_total") != 8
        or ab_summary.get("ab_critical_regressions") != 0
    ):
        raise ArtifactFailure("MEMORY_AB_FAILED")
    baseline_checks = baselines.get("release_checks")
    if baselines.get("overall_status") != "passed" or not isinstance(
        baseline_checks, dict
    ):
        raise ArtifactFailure("FOUR_BASELINES_FAILED")

    baseline_rows = [
        _baseline_summary(baselines, name)
        for name in ("no_memory", "full_history", "retrieval_only", "memtrace")
    ]
    if any(
        row.get("completed") != 16 or row.get("expected") != 16 for row in baseline_rows
    ):
        raise ArtifactFailure("FOUR_BASELINES_INCOMPLETE")
    memtrace = _baseline_summary(baselines, "memtrace")
    full_history = _baseline_summary(baselines, "full_history")
    untouched_summary = untouched["summary"]

    candidate_commit = args.candidate_commit
    if candidate_commit is not None and (
        len(candidate_commit) != 40
        or any(char not in "0123456789abcdef" for char in candidate_commit)
    ):
        raise ArtifactFailure("CANDIDATE_COMMIT_INVALID")
    release_status = "semantic_gates_passed"
    if args.mark_release_passed:
        if candidate_commit is None:
            raise ArtifactFailure("PASSED_RELEASE_REQUIRES_COMMIT")
        release_status = "passed"

    return {
        "schema_version": "1.1.0",
        "release_status": release_status,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "candidate_commit": candidate_commit,
        "model": model,
        "semantic_fixture_sha256": _sha256(args.semantic_fixture),
        "ab_fixture_sha256": _sha256(args.ab_fixture),
        "baseline_fixture_sha256": _sha256(args.baseline_fixture),
        "split": "g5_day7_frozen_v1",
        "config_selection": "validation_grid_v1",
        "selected_config": {
            "auto_activate_threshold": selected_config["auto_activate_threshold"],
            "per_card_token_budget": selected_config["per_card_token_budget"],
            "total_token_budget": selected_config["total_token_budget"],
        },
        "gates": {
            "provider_preflight": _passed_gate(6, 6),
            "validation_semantic": validation_gate,
            "semantic_test": untouched_gate,
            "memory_ab": _passed_gate(int(ab_summary["ab_total"]), 8),
            "four_baselines": _passed_gate(
                int(baseline_checks["workflows_completed"]), 64
            ),
        },
        "metrics": {
            "untouched_test_passes": int(untouched_summary["semantic_passed"]),
            "untouched_test_expected": 16,
            "activation_precision": float(untouched_summary["activation_precision"]),
            "safety_false_activations": int(untouched_summary["security_failures"]),
            "memory_ab_wins": int(ab_summary["ab_memory_on_wins"]),
            "memory_ab_cases": 8,
            "memtrace_not_worse_cases": int(
                baseline_checks["memtrace_not_worse_cases"]
            ),
            "memtrace_comparison_cases": 8,
            "memtrace_median_input_tokens": int(memtrace["median_input_tokens"]),
            "full_history_median_input_tokens": int(
                full_history["median_input_tokens"]
            ),
            "p95_first_token_ms": float(baseline_checks["p95_first_token_ms"]),
            "p95_total_latency_ms": max(
                float(row["p95_latency_ms"]) for row in baseline_rows
            ),
        },
        "baselines": baseline_rows,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-preflight", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--untouched-test", type=Path, required=True)
    parser.add_argument("--memory-ab", type=Path, required=True)
    parser.add_argument("--four-baselines", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument(
        "--semantic-fixture",
        type=Path,
        default=PROJECT_ROOT / "fixtures/day6/semantic_cases.json",
    )
    parser.add_argument(
        "--ab-fixture",
        type=Path,
        default=PROJECT_ROOT / "fixtures/day6/ab_cases.json",
    )
    parser.add_argument(
        "--baseline-fixture",
        type=Path,
        default=PROJECT_ROOT / "fixtures/day7/baseline_cases.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-commit")
    parser.add_argument("--mark-release-passed", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        artifact = build(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (ArtifactFailure, OSError, KeyError, TypeError, ValueError) as exc:
        failure_code = (
            str(exc) if isinstance(exc, ArtifactFailure) else "ARTIFACT_BUILD_FAILED"
        )
        print(json.dumps({"status": "failed", "failure_code": failure_code}))
        return 2
    print(
        json.dumps(
            {
                "status": "passed",
                "release_status": artifact["release_status"],
                "model": artifact["model"],
                "secrets_printed": False,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
