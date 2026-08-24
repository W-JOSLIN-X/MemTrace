"""Local readiness checks; no external provider request is performed here."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

API_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = API_ROOT / "alembic"


class DatabaseRevisionError(RuntimeError):
    """Raised when the database revision is absent, stale, or ambiguous."""


def ensure_directory_writable(path: Path) -> None:
    """Create the runtime directory and verify an actual file can be written."""

    path.mkdir(parents=True, exist_ok=True)
    file_descriptor, probe_path = tempfile.mkstemp(prefix=".ready-", dir=path)
    try:
        os.close(file_descriptor)
    finally:
        Path(probe_path).unlink(missing_ok=True)


def ensure_database_current(session: Session) -> str:
    """Verify connectivity and require the database to match the unique Alembic head."""
    session.execute(text("SELECT 1"))
    heads = ScriptDirectory(str(MIGRATIONS_DIR)).get_heads()
    if len(heads) != 1:
        raise DatabaseRevisionError("migration history must expose exactly one head")
    expected_head = heads[0]
    current_revision = MigrationContext.configure(session.connection()).get_current_revision()
    if current_revision != expected_head:
        raise DatabaseRevisionError("database revision does not match migration head")
    return expected_head
