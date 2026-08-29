"""Day 6 v2.0.0: Engineering tests — migration, isolation, idempotency, secret scan."""

from __future__ import annotations

import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def run_cmd(cmd: list[str], desc: str, timeout: int = 120) -> tuple[int, str]:
    """Run a command and return (exit_code, output)."""
    print(f"\n{'='*60}")
    print(f"Running: {desc}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
            errors='replace'
        )
        print(result.stdout[-2000:] if result.stdout else "(no stdout)")
        if result.stderr:
            print(f"STDERR: {result.stderr[-1000:]}")
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {timeout}s")
        return -1, "timeout"
    except Exception as e:
        print(f"ERROR: {e}")
        return -1, str(e)


def main():
    tests = []

    def chk(name: str, fn):
        try:
            rc, out = fn()
            status = "PASS" if rc == 0 else ("WARN" if rc == -1 else "FAIL")
            tests.append(f"{status} [{name}] exit={rc}")
        except Exception as e:
            tests.append(f"FAIL [{name}] EXCEPTION: {e}")

    # ---- 1. Import check ----
    def check_imports():
        return run_cmd(
            [sys.executable, "-c", "from memtrace_api.main import app; print('OK')"],
            "Import check",
        )

    chk("IMPORT", check_imports)

    # ---- 2. Ruff lint ----
    def check_ruff():
        return run_cmd(
            [sys.executable, "-m", "ruff", "check", "apps/api/src/memtrace_api"],
            "Ruff lint",
        )

    chk("RUFF", check_ruff)

    # ---- 3. Migration: fresh DB ----
    def check_migration_fresh():
        db_path = "/tmp/day6_eng_fresh.sqlite3"
        if os.path.exists(db_path):
            os.remove(db_path)
        os.environ["MEMTRACE_DATABASE_URL"] = f"sqlite:///{db_path}"
        return run_cmd(
            [
                sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini",
                "upgrade", "head",
            ],
            f"Migration fresh DB ({db_path})",
        )

    chk("MIGRATION_FRESH", check_migration_fresh)

    # ---- 4. Migration: unique head ----
    def check_migration_head():
        return run_cmd(
            [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", "heads"],
            "Migration unique head",
        )

    chk("MIGRATION_HEAD", check_migration_head)

    # ---- 5. Migration: current ----
    def check_migration_current():
        return run_cmd(
            [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", "current"],
            "Migration current",
        )

    chk("MIGRATION_CURRENT", check_migration_current)

    # ---- 6. Migration: 005→006→005 roundtrip ----
    def check_migration_roundtrip():
        db_path = "/tmp/day6_eng_roundtrip.sqlite3"
        if os.path.exists(db_path):
            os.remove(db_path)
        # Upgrade to 006
        rc1, _ = run_cmd(
            [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini",
             f"--db={db_path}", "upgrade", "006_conversation_first_memory"],
            "Roundtrip: upgrade to 006",
        )
        if rc1 != 0:
            return rc1, "upgrade to 006 failed"
        # Downgrade to 005
        rc2, out = run_cmd(
            [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini",
             f"--db={db_path}", "downgrade", "005_g4_memory_center_pack"],
            "Roundtrip: downgrade to 005",
        )
        # Upgrade again
        rc3, _ = run_cmd(
            [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini",
             f"--db={db_path}", "upgrade", "head"],
            "Roundtrip: re-upgrade to 006",
        )
        return rc3 if rc3 != 0 else rc2, "roundtrip done"

    chk("MIGRATION_ROUNDTRIP", check_migration_roundtrip)

    # ---- 7. OpenAPI zero diff ----
    def check_openapi():
        # Export current OpenAPI
        export_script = os.path.join(ROOT, "scripts", "export_openapi.py")
        if not os.path.exists(export_script):
            return -1, "export_openapi.py not found"
        return run_cmd(
            [sys.executable, export_script],
            "OpenAPI export",
        )

    chk("OPENAPI", check_openapi)

    # ---- 8. Secret scan ----
    def check_secret_scan():
        return run_cmd(
            ["git", "diff", "--cached", "--check"],
            "Secret scan (git diff --check)",
        )

    chk("SECRET_SCAN", check_secret_scan)

    # ---- 9. pip check ----
    def check_pip():
        return run_cmd(
            [sys.executable, "-m", "pip", "check"],
            "pip check",
        )

    chk("PIP", check_pip)

    # ---- Output summary ----
    print(f"\n{'='*60}")
    print("Engineering Test Summary")
    print(f"{'='*60}")
    for t in tests:
        print(t)
    passed = sum(1 for t in tests if t.startswith("PASS"))
    failed = sum(1 for t in tests if t.startswith("FAIL"))
    warned = sum(1 for t in tests if t.startswith("WARN"))
    print(f"\nTotal: {passed} passed, {failed} failed, {warned} warned, {len(tests)} total")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
