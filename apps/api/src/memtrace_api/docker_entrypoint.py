"""Migrate the persistent database, then replace this process with Uvicorn."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    api_root = Path(__file__).resolve().parents[2]
    repository_root = api_root.parents[1]
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(api_root / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=repository_root,
        check=True,
    )
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "memtrace_api.main:app",
            "--app-dir",
            str(api_root / "src"),
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "1",
        ],
    )


if __name__ == "__main__":
    main()
