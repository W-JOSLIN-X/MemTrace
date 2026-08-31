"""Migrate the persistent database, then replace this process with Uvicorn."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from memtrace_api.config import normalize_trusted_proxy_ips


def build_uvicorn_command(api_root: Path, environ: Mapping[str, str]) -> list[str]:
    """Build a fail-closed Uvicorn command for the release container."""

    trusted_proxy_ips = normalize_trusted_proxy_ips(environ.get("TRUSTED_PROXY_IPS"))
    app_env = environ.get("APP_ENV", "development").strip().lower()
    if app_env == "production" and not trusted_proxy_ips:
        raise RuntimeError("TRUSTED_PROXY_IPS is required in production")

    command = [
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
        "--no-access-log",
    ]
    if trusted_proxy_ips:
        command.extend(
            [
                "--proxy-headers",
                "--forwarded-allow-ips",
                trusted_proxy_ips,
            ]
        )
    else:
        command.append("--no-proxy-headers")
    return command


def main() -> None:
    api_root = Path(__file__).resolve().parents[2]
    repository_root = api_root.parents[1]
    server_command = build_uvicorn_command(api_root, os.environ)
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
        server_command,
    )


if __name__ == "__main__":
    main()
