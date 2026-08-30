"""Restore a verified MemTrace SQLite backup into a new destination file."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quick_check(connection: sqlite3.Connection) -> str:
    result = connection.execute("PRAGMA quick_check").fetchone()
    if result is None or result[0] != "ok":
        raise RuntimeError("SQLite quick_check failed")
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if revision is None:
        raise RuntimeError("backup has no Alembic revision")
    return str(revision[0])


def restore_backup(
    backup: Path,
    destination: Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    backup = backup.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite destination: {destination}")
    actual_hash = _sha256(backup)
    if expected_sha256 is not None and not hmac.compare_digest(
        actual_hash,
        expected_sha256.casefold(),
    ):
        raise RuntimeError("backup SHA-256 does not match --expected-sha256")
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".restore",
        dir=destination.parent,
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        with closing(
            sqlite3.connect(backup.as_uri() + "?mode=ro&immutable=1", uri=True)
        ) as source_db:
            revision = _quick_check(source_db)
            with closing(sqlite3.connect(temporary)) as destination_db:
                source_db.backup(destination_db)
                destination_db.commit()
                restored_revision = _quick_check(destination_db)
        if revision != restored_revision:
            raise RuntimeError("restored Alembic revision changed during backup")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "backup": str(backup),
        "backup_sha256": actual_hash,
        "destination": str(destination),
        "migration_revision": revision,
        "quick_check": "ok",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    try:
        print(
            json.dumps(
                restore_backup(
                    args.backup,
                    args.destination,
                    expected_sha256=args.expected_sha256,
                ),
                sort_keys=True,
            )
        )
        return 0
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
