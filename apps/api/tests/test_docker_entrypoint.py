from __future__ import annotations

import sys
from pathlib import Path

import pytest

from memtrace_api import docker_entrypoint


def test_docker_entrypoint_migrates_before_execing_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str], Path | None]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert check is True
        calls.append(("run", command, cwd))

    def fake_execv(executable: str, command: list[str]) -> None:
        calls.append(("execv", command, None))
        assert executable == sys.executable

    monkeypatch.setattr(docker_entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(docker_entrypoint.os, "execv", fake_execv)

    docker_entrypoint.main()

    assert [name for name, _, _ in calls] == ["run", "execv"]
    migration = calls[0][1]
    server = calls[1][1]
    assert migration[-2:] == ["upgrade", "head"]
    assert migration[1:3] == ["-m", "alembic"]
    assert server[1:4] == ["-m", "uvicorn", "memtrace_api.main:app"]
