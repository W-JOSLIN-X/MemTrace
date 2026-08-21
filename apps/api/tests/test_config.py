from __future__ import annotations

import logging
import sys
from pathlib import Path

from memtrace_api.config import DEFAULT_DATA_DIR, PROJECT_ROOT, Settings
from memtrace_api.logging_config import RedactingFormatter, SecretRedactionFilter


def test_env_file_is_absolute_repository_root_path() -> None:
    env_file = Settings.model_config["env_file"]
    assert Path(env_file).is_absolute()
    assert Path(env_file) == PROJECT_ROOT / ".env"


def test_relative_data_dir_is_resolved_against_repository() -> None:
    settings = Settings(_env_file=None, memtrace_data_dir="runtime-data")
    assert settings.memtrace_data_dir == (PROJECT_ROOT / "runtime-data").resolve()


def test_blank_values_use_safe_defaults() -> None:
    settings = Settings(_env_file=None, llm_api_key="", memtrace_data_dir="")
    assert settings.llm_api_key is None
    assert settings.memtrace_data_dir == DEFAULT_DATA_DIR


def test_secret_is_masked_in_settings_and_logs() -> None:
    secret = "unit-test-secret-value"
    settings = Settings(_env_file=None, llm_api_key=secret)
    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="credential=%s Authorization=Bearer %s",
        args=(secret, secret),
        exc_info=None,
    )
    SecretRedactionFilter([secret]).filter(record)
    assert secret not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_redaction_preserves_numeric_logging_placeholders() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="duration_ms=%.2f",
        args=(12.345,),
        exc_info=None,
    )
    SecretRedactionFilter().filter(record)
    assert record.getMessage() == "duration_ms=12.35"


def test_formatter_redacts_exception_message() -> None:
    secret = "exception-secret-value"
    try:
        raise RuntimeError(f"provider rejected {secret}")
    except RuntimeError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="provider failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    rendered = RedactingFormatter("%(message)s", secrets=[secret]).format(record)
    assert secret not in rendered
    assert "[REDACTED]" in rendered
