"""Local readiness checks; no external provider request is performed here."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def ensure_directory_writable(path: Path) -> None:
    """Create the runtime directory and verify an actual file can be written."""

    path.mkdir(parents=True, exist_ok=True)
    file_descriptor, probe_path = tempfile.mkstemp(prefix=".ready-", dir=path)
    try:
        os.close(file_descriptor)
    finally:
        Path(probe_path).unlink(missing_ok=True)
