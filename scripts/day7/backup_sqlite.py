"""Create a consistent MemTrace SQLite backup with the SQLite backup API."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quick_check(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA quick_check").fetchone()
    if result is None or result[0] != "ok":
        raise RuntimeError("SQLite quick_check failed")


def create_backup(source: Path, output: Path) -> dict[str, object]:
    source = source.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing backup: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    source_uri = source.as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(source_uri, uri=True)) as source_db:
            _quick_check(source_db)
            with closing(sqlite3.connect(output)) as output_db:
                source_db.backup(output_db)
                output_db.commit()
                _quick_check(output_db)
                revision_row = output_db.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()
    except Exception:
        output.unlink(missing_ok=True)
        raise
    if revision_row is None:
        output.unlink(missing_ok=True)
        raise RuntimeError("backup has no Alembic revision")
    return {
        "backup": str(output),
        "bytes": output.stat().st_size,
        "sha256": _sha256(output),
        "migration_revision": revision_row[0],
        "quick_check": "ok",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(create_backup(args.source, args.output), sort_keys=True))
        return 0
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
