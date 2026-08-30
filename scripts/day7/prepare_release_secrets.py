"""Prepare ignored Docker secret files without printing secret material."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

from dotenv import dotenv_values


class SecretPreparationFailure(RuntimeError):
    """Controlled secret preparation failure."""


def _read_key(env_file: Path) -> str:
    try:
        values = dotenv_values(env_file)
    except (OSError, UnicodeDecodeError) as exc:
        raise SecretPreparationFailure("ENV_FILE_UNREADABLE") from exc
    inline = values.get("LLM_API_KEY")
    key_file = values.get("LLM_API_KEY_FILE")
    if isinstance(inline, str) and inline.strip():
        value = inline.strip()
    elif isinstance(key_file, str) and key_file.strip():
        path = Path(key_file.strip())
        if not path.is_absolute():
            path = env_file.parent / path
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise SecretPreparationFailure("LLM_KEY_FILE_UNREADABLE") from exc
    else:
        raise SecretPreparationFailure("LLM_API_KEY_MISSING")
    if (
        len(value) < 16
        or len(value.encode("utf-8")) > 4_096
        or "\x00" in value
        or "\n" in value
        or "\r" in value
        or value.startswith("<")
    ):
        raise SecretPreparationFailure("LLM_API_KEY_INVALID")
    return value


def prepare(env_file: Path, output_dir: Path) -> dict[str, object]:
    key = _read_key(env_file.resolve(strict=True))
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        "llm_api_key": key + "\n",
        "session_secret": secrets.token_urlsafe(48) + "\n",
    }
    if any((output_dir / name).exists() for name in targets):
        raise SecretPreparationFailure("SECRET_TARGET_ALREADY_EXISTS")
    created: list[Path] = []
    try:
        for name, value in targets.items():
            target = output_dir / name
            with target.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(value)
            os.chmod(target, 0o600)
            created.append(target)
    except OSError as exc:
        for target in created:
            target.unlink(missing_ok=True)
        raise SecretPreparationFailure("SECRET_WRITE_FAILED") from exc
    return {
        "status": "passed",
        "has_llm_api_key": True,
        "session_secret_generated": True,
        "secret_values_printed": False,
        "file_count": len(created),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.env_file, args.output_dir)
    except SecretPreparationFailure as exc:
        print(json.dumps({"status": "failed", "failure_code": str(exc)}))
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
