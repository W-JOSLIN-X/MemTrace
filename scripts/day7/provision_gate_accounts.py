"""Provision isolated public release-gate accounts without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

USERNAME_PATTERN = re.compile(r"^[a-z0-9_]{3,32}$")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_SRC = PROJECT_ROOT / "apps/api/src"


class ProvisionFailure(RuntimeError):
    """Controlled account-provisioning failure without upstream body leakage."""


def _create_invite() -> str:
    child_environment = dict(os.environ)
    child_environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(API_SRC), child_environment.get("PYTHONPATH", "")) if part
    )
    result = subprocess.run(
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
        capture_output=True,
        text=True,
        check=False,
        cwd=PROJECT_ROOT,
        env=child_environment,
    )
    if result.returncode != 0:
        raise ProvisionFailure("INVITE_CREATE_FAILED")
    try:
        payload = json.loads(result.stdout)
        code = payload["invitation_code"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProvisionFailure("INVITE_RESPONSE_INVALID") from exc
    if not isinstance(code, str) or len(code) < 20:
        raise ProvisionFailure("INVITE_RESPONSE_INVALID")
    return code


def _register(base_url: str, origin: str, username: str, password: str) -> str:
    invitation_code = _create_invite()
    body = json.dumps(
        {
            "invitation_code": invitation_code,
            "username": username,
            "display_name": f"Gate {username}",
            "password": password,
            "password_confirmation": password,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v2/auth/register",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Origin": origin},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.status
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProvisionFailure(f"REGISTER_HTTP_{exc.code}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvisionFailure("REGISTER_TRANSPORT_OR_RESPONSE_INVALID") from exc
    recovery_code = payload.get("recovery_code") if isinstance(payload, dict) else None
    if status != 201 or not isinstance(recovery_code, str) or len(recovery_code) < 20:
        raise ProvisionFailure("REGISTER_RESPONSE_INVALID")
    return recovery_code


def _write_secret(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, (value + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--username", action="append", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    usernames = list(dict.fromkeys(args.username))
    if len(usernames) != len(args.username) or any(
        USERNAME_PATTERN.fullmatch(username) is None for username in usernames
    ):
        print(json.dumps({"status": "failed", "failure_code": "USERNAME_INVALID"}))
        return 2
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "credentials.manifest.json"
    if manifest_path.exists():
        print(json.dumps({"status": "failed", "failure_code": "OUTPUT_ALREADY_EXISTS"}))
        return 2

    manifest: dict[str, object] = {"schema_version": "1.0", "accounts": []}
    try:
        for username in usernames:
            password_path = output_dir / f"{username}.password"
            recovery_path = output_dir / f"{username}.recovery"
            if password_path.exists() or recovery_path.exists():
                raise ProvisionFailure("OUTPUT_ALREADY_EXISTS")
            password = "D7!" + secrets.token_urlsafe(24)
            recovery_code = _register(args.base_url, args.origin, username, password)
            _write_secret(password_path, password)
            _write_secret(recovery_path, recovery_code)
            manifest["accounts"].append(
                {
                    "username": username,
                    "password_file": password_path.name,
                    "recovery_file": recovery_path.name,
                }
            )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ProvisionFailure) as exc:
        failure_code = str(exc) if isinstance(exc, ProvisionFailure) else "FILE_ERROR"
        print(json.dumps({"status": "failed", "failure_code": failure_code}))
        return 2

    print(
        json.dumps(
            {
                "status": "passed",
                "created": len(usernames),
                "manifest": str(manifest_path),
                "secrets_printed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
