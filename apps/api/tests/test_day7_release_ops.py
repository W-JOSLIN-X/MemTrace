"""Day 7 release operations, runtime-lock, and evaluator-boundary tests."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from memtrace_api.public_auth import _secret_hash

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKUP_SCRIPT = PROJECT_ROOT / "scripts/day7/backup_sqlite.py"
RESTORE_SCRIPT = PROJECT_ROOT / "scripts/day7/restore_sqlite.py"
CALIBRATION_SCRIPT = PROJECT_ROOT / "scripts/day7/calibrate_config.py"
PREPARE_SECRETS_SCRIPT = PROJECT_ROOT / "scripts/day7/prepare_release_secrets.py"
PROVISION_ACCOUNTS_SCRIPT = PROJECT_ROOT / "scripts/day7/provision_gate_accounts.py"


def _load_calibrate():
    spec = importlib.util.spec_from_file_location("day7_calibrate_config", CALIBRATION_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.calibrate


def _load_provision_accounts():
    spec = importlib.util.spec_from_file_location(
        "day7_provision_gate_accounts", PROVISION_ACCOUNTS_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_json(script: Path, *arguments: str) -> tuple[int, dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def test_sqlite_backup_and_restore_are_consistent_and_refuse_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backups" / "release.sqlite3"
    restored = tmp_path / "restored" / "memtrace.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        connection.execute(
            "INSERT INTO alembic_version(version_num) VALUES (?)",
            ("007_day7_public_release",),
        )
        connection.execute("CREATE TABLE synthetic (value TEXT NOT NULL)")
        connection.execute("INSERT INTO synthetic(value) VALUES ('release-proof')")

    backup_code, backup_report = _run_json(
        BACKUP_SCRIPT,
        "--source",
        str(source),
        "--output",
        str(backup),
    )
    restore_code, restore_report = _run_json(
        RESTORE_SCRIPT,
        "--backup",
        str(backup),
        "--destination",
        str(restored),
        "--expected-sha256",
        str(backup_report["sha256"]),
    )
    assert backup_code == restore_code == 0, (backup_report, restore_report)
    assert backup_report["migration_revision"] == "007_day7_public_release"
    assert restore_report["migration_revision"] == "007_day7_public_release"
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT value FROM synthetic").fetchone() == ("release-proof",)
    assert (
        _run_json(
            BACKUP_SCRIPT,
            "--source",
            str(source),
            "--output",
            str(backup),
        )[0]
        == 2
    )
    assert (
        _run_json(
            RESTORE_SCRIPT,
            "--backup",
            str(backup),
            "--destination",
            str(restored),
        )[0]
        == 2
    )


def test_restore_rejects_hash_mismatch_without_creating_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        connection.execute(
            "INSERT INTO alembic_version(version_num) VALUES (?)",
            ("007_day7_public_release",),
        )
    assert (
        _run_json(
            BACKUP_SCRIPT,
            "--source",
            str(source),
            "--output",
            str(backup),
        )[0]
        == 0
    )
    code, report = _run_json(
        RESTORE_SCRIPT,
        "--backup",
        str(backup),
        "--destination",
        str(destination),
        "--expected-sha256",
        "0" * 64,
    )
    assert code == 2
    assert report["error"] == "RuntimeError"
    assert "SHA-256" in str(report["message"])
    assert not destination.exists()


def test_restore_opens_verified_static_backup_as_immutable() -> None:
    restore_source = RESTORE_SCRIPT.read_text("utf-8")
    assert "?mode=ro&immutable=1" in restore_source


def test_release_secret_preparation_is_quiet_and_refuses_overwrite(tmp_path: Path) -> None:
    synthetic_key = "synthetic-release-credential-never-valid"
    env_file = tmp_path / ".env"
    secret_dir = tmp_path / "secrets"
    env_file.write_text(f"LLM_API_KEY={synthetic_key}\n", encoding="utf-8")
    code, report = _run_json(
        PREPARE_SECRETS_SCRIPT,
        "--env-file",
        str(env_file),
        "--output-dir",
        str(secret_dir),
    )
    assert code == 0
    assert report == {
        "file_count": 2,
        "has_llm_api_key": True,
        "secret_values_printed": False,
        "session_secret_generated": True,
        "status": "passed",
    }
    assert synthetic_key not in json.dumps(report)
    assert (secret_dir / "llm_api_key").read_text("utf-8").strip() == synthetic_key
    assert len((secret_dir / "session_secret").read_text("utf-8").strip()) >= 43
    retry_code, retry_report = _run_json(
        PREPARE_SECRETS_SCRIPT,
        "--env-file",
        str(env_file),
        "--output-dir",
        str(secret_dir),
    )
    assert retry_code == 2
    assert retry_report["failure_code"] == "SECRET_TARGET_ALREADY_EXISTS"


def test_release_account_provisioner_uses_bounded_container_admin_cli(monkeypatch) -> None:
    module = _load_provision_accounts()
    invitation_code = "inv_" + "s" * 43
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"invitation_code": invitation_code}),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module._create_invite("memtrace-d7-release-gate-app-1") == invitation_code
    assert captured["command"] == [
        "docker",
        "exec",
        "memtrace-d7-release-gate-app-1",
        "python",
        "-m",
        "memtrace_api.admin_cli",
        "invite-create",
        "--max-uses",
        "1",
        "--expires-hours",
        "24",
    ]
    assert module.CONTAINER_PATTERN.fullmatch("../../another-container") is None


def test_release_runtime_lock_contains_production_imports_but_excludes_dev_tools() -> None:
    runtime_lock = (PROJECT_ROOT / "apps/api/requirements.runtime.lock").read_text("utf-8")
    lowered = runtime_lock.casefold()
    assert "jsonschema==4.26.0" in lowered
    for forbidden in ("pytest==", "ruff==", "httpx2==", "vitest"):
        assert forbidden not in lowered
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text("utf-8")
    assert "--require-hashes --no-deps" in dockerfile
    assert "requirements.runtime.lock" in dockerfile


def test_day7_external_runners_do_not_import_backend_modules() -> None:
    for relative in (
        "scripts/day3/eval_runner.py",
        "scripts/day4/eval_runner.py",
        "scripts/day5/eval_runner.py",
        "scripts/day6/eval_runner.py",
        "scripts/day7/baseline_runner.py",
        "scripts/day7/build_eval_artifact.py",
        "scripts/day7/calibrate_config.py",
    ):
        tree = ast.parse((PROJECT_ROOT / relative).read_text("utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            name == "memtrace_api" or name.startswith("memtrace_api.") for name in imported
        )


def test_secret_hash_is_one_way_and_does_not_embed_plaintext() -> None:
    secret = "synthetic-one-time-secret"
    digest = _secret_hash(secret)
    assert len(digest) == 64
    assert secret not in digest


def test_admin_cli_shows_invite_once_and_lists_metadata_only(tmp_db_url: str) -> None:
    env = dict(
        os.environ,
        MEMTRACE_DATABASE_URL=tmp_db_url,
        PYTHONPATH=str(PROJECT_ROOT / "apps/api/src"),
        APP_ENV="test",
        MOCK_MODE="true",
        SESSION_SECRET="release-ops-test-secret-0123456789",
    )
    created = subprocess.run(
        [
            sys.executable,
            "-m",
            "memtrace_api.admin_cli",
            "invite-create",
            "--max-uses",
            "1",
            "--expires-hours",
            "24",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    created_body = json.loads(created.stdout)
    invite_secret = created_body.pop("invitation_code")
    assert isinstance(invite_secret, str) and invite_secret.startswith("inv_")

    listed = subprocess.run(
        [sys.executable, "-m", "memtrace_api.admin_cli", "invite-list"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert listed.returncode == 0, listed.stderr
    assert invite_secret not in listed.stdout
    listed_body = json.loads(listed.stdout)
    assert listed_body["invites"] == [
        {
            "created_at": listed_body["invites"][0]["created_at"],
            "expires_at": listed_body["invites"][0]["expires_at"],
            "invite_id": created_body["invite_id"],
            "max_uses": 1,
            "status": "active",
            "use_count": 0,
        }
    ]
    assert "hash" not in listed.stdout.casefold()


class _CalibrationRest:
    def request(self, method: str, path: str):
        assert method == "GET"
        memory_id = path.split("/")[4]
        index = int(memory_id.removeprefix("mem_test_"))
        if path.endswith("/usages?limit=100"):
            return 200, {"items": [{"estimated_tokens": 90 if index == 1 else 50}]}
        return 200, {"memory": {"confidence": 0.95}}


def test_validation_grid_selects_frozen_default_after_real_metadata_replay() -> None:
    rows = []
    for index in range(1, 17):
        positive = index <= 8
        case_id = (
            "g5-13-prompt-injection-safe-reject" if index == 13 else f"g5-{index:02d}-synthetic"
        )
        rows.append(
            {
                "status": "passed",
                "case_id": case_id,
                "expected_injected": positive,
                "injected_actual": positive,
                "resource_ids": {"memory_ids": [f"mem_test_{index}"] if positive else []},
                "usage": {"total_tokens": 100 + index, "latency_ms": 1_000 + index},
            }
        )
    report = {
        "provider_mode": "real",
        "model": "deepseek-v4-flash",
        "summary": {"overall_status": "passed"},
        "semantic": rows,
    }

    result = _load_calibrate()(report, _CalibrationRest())

    assert result["comparison_count"] == 9
    assert result["selected_config"] == {
        "auto_activate_threshold": 0.85,
        "per_card_token_budget": 100,
        "total_token_budget": 300,
    }
    assert all(row["security_false_activations"] == 0 for row in result["grid"])
    assert [
        row["semantic_passes"] for row in result["grid"] if row["per_card_token_budget"] == 80
    ] == [15, 15, 15]


def test_release_compose_and_dockerfile_keep_secrets_and_dev_tools_out() -> None:
    compose = (PROJECT_ROOT / "compose.release.yaml").read_text("utf-8")
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text("utf-8")
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text("utf-8")
    assert 'MOCK_MODE: "false"' in compose
    assert 'ALLOW_DEMO_SESSIONS: "false"' in compose
    assert 'COOKIE_SECURE: "${COOKIE_SECURE:-true}"' in compose
    assert 'IMPORT_PREVIEW_TTL_SECONDS: "${IMPORT_PREVIEW_TTL_SECONDS:-1800}"' in compose
    assert "LLM_API_KEY_FILE: /run/secrets/llm_api_key" in compose
    assert "SESSION_SECRET_FILE: /run/secrets/session_secret" in compose
    assert "LLM_API_KEY:" not in compose
    assert "requirements.runtime.lock" in dockerfile
    assert "COPY apps/api/requirements.lock" not in dockerfile
    for required_context_path in (
        "!contracts/schemas/memory-pack-v2.schema.json",
        "!scripts/day7/backup_sqlite.py",
        "!scripts/day7/restore_sqlite.py",
    ):
        assert required_context_path in dockerignore


def test_production_security_headers_and_request_body_limit(client_factory) -> None:
    with client_factory(
        app_env="production",
        cookie_secure=True,
        max_request_body_bytes=1_024,
    ) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["strict-transport-security"].startswith("max-age=31536000")

        oversized = client.post(
            "/api/v2/auth/login",
            content=json.dumps({"username": "user", "password": "x" * 1_100}),
            headers={"content-type": "application/json"},
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "VALIDATION_ERROR"

        oversized_pack = client.post(
            "/api/v2/memory-packs/import/preview",
            content=b"{" + b" " * 1_100,
            headers={"content-type": "application/json"},
        )
        assert oversized_pack.status_code == 413
        assert oversized_pack.json()["error"]["code"] == "MEMORY_PACK_TOO_LARGE"
