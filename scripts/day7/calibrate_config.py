"""Select the Day 7 threshold and memory budget from real validation metadata."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVAL_RUNNER = PROJECT_ROOT / "scripts/day6/eval_runner.py"


def _load_eval_runner():
    spec = importlib.util.spec_from_file_location(
        "memtrace_day6_eval_runner", EVAL_RUNNER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("DAY6_EVAL_RUNNER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_eval_runner = _load_eval_runner()
GateFailure = _eval_runner.GateFailure
RestClient = _eval_runner.RestClient

THRESHOLDS = (0.8, 0.85, 0.9)
BUDGETS = ((80, 240), (100, 300), (120, 360))
DEFAULT_CONFIG = (0.85, 100, 300)


def _load_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateFailure("CALIBRATION_REPORT_INVALID") from exc
    if not isinstance(value, dict):
        raise GateFailure("CALIBRATION_REPORT_INVALID")
    rows = value.get("semantic")
    if (
        value.get("provider_mode") != "real"
        or value.get("summary", {}).get("overall_status") != "passed"
        or not isinstance(rows, list)
        or len(rows) != 16
        or any(
            not isinstance(row, dict) or row.get("status") != "passed" for row in rows
        )
    ):
        raise GateFailure("CALIBRATION_REPORT_NOT_PASSED")
    return value


def _credential(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GateFailure("CALIBRATION_CREDENTIAL_UNREADABLE") from exc
    if not value or len(value.encode("utf-8")) > 1_024:
        raise GateFailure("CALIBRATION_CREDENTIAL_INVALID")
    return value


def _memory_metadata(rest: RestClient, memory_id: str) -> tuple[float, int]:
    status, detail = rest.request("GET", f"/api/v2/memories/{memory_id}")
    if status != 200 or not isinstance(detail, dict):
        raise GateFailure("CALIBRATION_MEMORY_UNREADABLE")
    memory = detail.get("memory")
    confidence = memory.get("confidence") if isinstance(memory, dict) else None
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise GateFailure("CALIBRATION_CONFIDENCE_INVALID")
    status, usage_page = rest.request(
        "GET",
        f"/api/v2/memories/{memory_id}/usages?limit=100",
    )
    items = (
        usage_page.get("items")
        if status == 200 and isinstance(usage_page, dict)
        else None
    )
    if not isinstance(items, list):
        raise GateFailure("CALIBRATION_USAGE_UNREADABLE")
    estimates = [
        item.get("estimated_tokens")
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("estimated_tokens"), int)
        and not isinstance(item.get("estimated_tokens"), bool)
    ]
    return float(confidence), max(estimates, default=0)


def _percentile(values: list[int], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise GateFailure("CALIBRATION_METRIC_EMPTY")
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * probability) - 1))
    return float(ordered[index])


def calibrate(report: dict[str, Any], rest: RestClient) -> dict[str, Any]:
    enriched: list[dict[str, Any]] = []
    for row in report["semantic"]:
        resource_ids = row.get("resource_ids")
        memory_ids = (
            resource_ids.get("memory_ids") if isinstance(resource_ids, dict) else None
        )
        if not isinstance(memory_ids, list) or any(
            not isinstance(item, str) for item in memory_ids
        ):
            raise GateFailure("CALIBRATION_RESOURCE_IDS_INVALID")
        metadata = [_memory_metadata(rest, memory_id) for memory_id in memory_ids]
        usage = row.get("usage")
        if not isinstance(usage, dict):
            raise GateFailure("CALIBRATION_WORKFLOW_USAGE_INVALID")
        total_tokens = usage.get("total_tokens")
        latency_ms = usage.get("latency_ms")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (total_tokens, latency_ms)
        ):
            raise GateFailure("CALIBRATION_WORKFLOW_USAGE_INVALID")
        enriched.append(
            {
                "case_id": row["case_id"],
                "expected_injected": bool(row["expected_injected"]),
                "injected_actual": bool(row["injected_actual"]),
                "security_case": row["case_id"] == "g5-13-prompt-injection-safe-reject",
                "confidences": [item[0] for item in metadata],
                "estimated_tokens": [item[1] for item in metadata],
                "workflow_total_tokens": total_tokens,
                "workflow_latency_ms": latency_ms,
            }
        )

    grid: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        for per_card, total_budget in BUDGETS:
            semantic_passes = 0
            true_positives = 0
            false_positives = 0
            security_false_activations = 0
            for row in enriched:
                auto_active = bool(row["confidences"]) and all(
                    confidence >= threshold for confidence in row["confidences"]
                )
                estimates = row["estimated_tokens"]
                budget_preserves_content = (
                    all(value <= per_card for value in estimates)
                    and sum(estimates) <= total_budget
                )
                simulated_injected = bool(
                    row["injected_actual"] and auto_active and budget_preserves_content
                )
                expected = row["expected_injected"]
                semantic_passes += int(simulated_injected == expected)
                true_positives += int(expected and simulated_injected)
                false_positives += int(not expected and simulated_injected)
                security_false_activations += int(
                    row["security_case"] and simulated_injected
                )
            precision = (
                1.0
                if true_positives + false_positives == 0
                else true_positives / (true_positives + false_positives)
            )
            grid.append(
                {
                    "auto_activate_threshold": threshold,
                    "per_card_token_budget": per_card,
                    "total_token_budget": total_budget,
                    "security_false_activations": security_false_activations,
                    "activation_precision": round(precision, 6),
                    "semantic_passes": semantic_passes,
                    "actual_total_tokens": sum(
                        row["workflow_total_tokens"] for row in enriched
                    ),
                    "p95_latency_ms": _percentile(
                        [row["workflow_latency_ms"] for row in enriched],
                        0.95,
                    ),
                }
            )

    def ranking(item: dict[str, Any]) -> tuple[object, ...]:
        config = (
            item["auto_activate_threshold"],
            item["per_card_token_budget"],
            item["total_token_budget"],
        )
        return (
            item["security_false_activations"],
            -item["activation_precision"],
            -item["semantic_passes"],
            item["actual_total_tokens"],
            item["p95_latency_ms"],
            config != DEFAULT_CONFIG,
            config,
        )

    selected = min(grid, key=ranking)
    if (
        selected["security_false_activations"] != 0
        or selected["activation_precision"] < 0.95
    ):
        raise GateFailure("CALIBRATION_SAFETY_OR_PRECISION_FAILED")
    if selected["semantic_passes"] != 16:
        raise GateFailure("CALIBRATION_SEMANTIC_FAILED")
    return {
        "schema_version": "1.0.0",
        "status": "passed",
        "provider_mode": "real",
        "model": report["model"],
        "source_report_sha256": hashlib.sha256(
            json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "case_count": len(enriched),
        "comparison_count": len(grid),
        "selection_order": [
            "security_false_activations",
            "activation_precision",
            "semantic_passes",
            "actual_total_tokens",
            "p95_latency_ms",
            "default_tie_break",
        ],
        "selected_config": {
            "auto_activate_threshold": selected["auto_activate_threshold"],
            "per_card_token_budget": selected["per_card_token_budget"],
            "total_token_budget": selected["total_token_budget"],
        },
        "grid": grid,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        report = _load_report(args.validation_report)
        rest = RestClient(
            args.base_url, timeout=60.0, auth_mode="public", origin=args.origin
        )
        rest.login(args.username, _credential(args.password_file))
        result = calibrate(report, rest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (GateFailure, OSError, KeyError, TypeError, ValueError) as exc:
        code = exc.code if isinstance(exc, GateFailure) else "CALIBRATION_FAILED"
        print(json.dumps({"status": "failed", "failure_code": code}))
        return 2
    print(
        json.dumps(
            {
                "status": "passed",
                "comparisons": result["comparison_count"],
                "selected_config": result["selected_config"],
                "secrets_printed": False,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
