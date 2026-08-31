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
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("TRUSTED_PROXY_IPS", raising=False)

    docker_entrypoint.main()

    assert [name for name, _, _ in calls] == ["run", "execv"]
    migration = calls[0][1]
    server = calls[1][1]
    assert migration[-2:] == ["upgrade", "head"]
    assert migration[1:3] == ["-m", "alembic"]
    assert server[1:4] == ["-m", "uvicorn", "memtrace_api.main:app"]
    assert "--no-access-log" in server
    assert "--no-proxy-headers" in server
    assert "--forwarded-allow-ips" not in server


def test_docker_entrypoint_enables_only_exact_trusted_proxy_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUSTED_PROXY_IPS", " 172.31.247.1,2001:0db8::1,172.31.247.1 ")
    monkeypatch.setattr(docker_entrypoint.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        docker_entrypoint.os,
        "execv",
        lambda _executable, command: commands.append(command),
    )

    docker_entrypoint.main()

    assert len(commands) == 1
    server = commands[0]
    assert "--proxy-headers" in server
    index = server.index("--forwarded-allow-ips")
    assert server[index + 1] == "172.31.247.1,2001:db8::1"
    assert "--no-proxy-headers" not in server
    assert "--no-access-log" in server


def test_docker_entrypoint_fails_before_migration_without_production_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TRUSTED_PROXY_IPS", raising=False)
    monkeypatch.setattr(
        docker_entrypoint.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("migration must not run"),
    )

    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_IPS is required"):
        docker_entrypoint.main()


@pytest.mark.parametrize(
    "value",
    ["*", "172.31.247.0/28", "proxy.internal", "172.31.247.1,", "fe80::1%eth0"],
)
def test_docker_entrypoint_rejects_broad_or_ambiguous_proxy_allowlists(value: str) -> None:
    api_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="TRUSTED_PROXY_IPS"):
        docker_entrypoint.build_uvicorn_command(
            api_root,
            {"APP_ENV": "production", "TRUSTED_PROXY_IPS": value},
        )
