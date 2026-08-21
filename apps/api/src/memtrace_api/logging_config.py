"""Logging configuration with explicit credential redaction."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

from memtrace_api.config import Settings

_TOKEN_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def redact_text(value: object, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        # Render first so numeric placeholders such as ``%.2f`` keep their
        # original types. Replacing every argument with a string would make
        # otherwise valid logging calls fail during formatting.
        record.msg = redact_text(record.getMessage(), self._secrets)
        record.args = ()
        return True


class RedactingFormatter(logging.Formatter):
    """Redact the final record, including exception text and tracebacks."""

    def __init__(self, *args: Any, secrets: Iterable[str] = (), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record), self._secrets)


def configure_logging(settings: Settings) -> None:
    secret_values: list[str] = []
    if settings.llm_api_key is not None:
        secret_values.append(settings.llm_api_key.get_secret_value())

    handler = logging.StreamHandler()
    handler.setFormatter(
        RedactingFormatter(
            fmt="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
            secrets=secret_values,
        )
    )
    handler.addFilter(SecretRedactionFilter(secret_values))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)


def safe_log_value(value: Any, settings: Settings) -> str:
    """Public helper for future provider logs to apply the same redaction policy."""

    secrets = [settings.llm_api_key.get_secret_value()] if settings.llm_api_key is not None else []
    return redact_text(value, secrets)
