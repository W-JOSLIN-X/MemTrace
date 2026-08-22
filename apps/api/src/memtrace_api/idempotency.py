"""Request hashing and idempotency helpers for write operations."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from memtrace_api.errors import ApiError, ErrorCode

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def validate_idempotency_key(key: str | None) -> str:
    """Validate Idempotency-Key header against the strict regex format."""
    if not key or not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=(
                "Idempotency-Key 格式无效，必须为 8–128 个 ASCII 字符"
                "（允许字母、数字、点、下划线、冒号、短横线）。"
            ),
        )
    return key


def compute_request_hash(
    *,
    method: str,
    path: str,
    body: dict[str, Any] | str,
) -> str:
    """Compute deterministic SHA-256 hash across method, path, and canonical json body."""
    if isinstance(body, dict):
        canonical_body = json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    else:
        canonical_body = body

    raw = f"{method.upper()}:{path}:{canonical_body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
