"""Dependency-free Crockford Base32 ULID generation."""

from __future__ import annotations

import secrets
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_ulid(value: int) -> str:
    chars = ["0"] * 26
    for index in range(25, -1, -1):
        value, remainder = divmod(value, 32)
        chars[index] = _CROCKFORD[remainder]
    return "".join(chars)


def new_prefixed_ulid(prefix: str) -> str:
    """Return ``<prefix>_<26-char ULID>`` using a 48-bit millisecond timestamp."""

    if not prefix or not prefix.isascii() or not prefix.isalpha():
        raise ValueError("ULID prefix must contain ASCII letters only")
    timestamp_ms = int(time.time_ns() // 1_000_000)
    if timestamp_ms >= 1 << 48:
        raise OverflowError("current timestamp exceeds ULID's 48-bit range")
    value = (timestamp_ms << 80) | secrets.randbits(80)
    return f"{prefix}_{_encode_ulid(value)}"
