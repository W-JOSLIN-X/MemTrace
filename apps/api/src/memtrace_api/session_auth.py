"""Demo session authentication, HMAC signing, and UserContext dependency."""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from typing import Annotated

from fastapi import Cookie, Request, Response

from memtrace_api.config import Settings
from memtrace_api.database import session_scope
from memtrace_api.errors import ApiError, ErrorCode
from memtrace_api.repositories import SessionRepository, UserContext

COOKIE_NAME = "memtrace_demo_session"
SESSION_DURATION = timedelta(hours=12)


def hash_token(token: str) -> str:
    """Compute SHA-256 of the random bearer token for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sign_cookie_value(raw_token: str, secret: str) -> str:
    """Generate `<token>.<signature>` with HMAC-SHA256."""
    sig = hmac.new(secret.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{raw_token}.{sig}"


def verify_cookie_value(cookie_value: str, secret: str) -> str | None:
    """Verify `<token>.<signature>` and return the raw token if valid, else None."""
    if not cookie_value or "." not in cookie_value:
        return None
    raw_token, provided_sig = cookie_value.split(".", 1)
    if not raw_token or not provided_sig:
        return None
    expected_sig = hmac.new(
        secret.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        return None
    return raw_token


def get_session_secret(settings: Settings) -> str:
    """Get validated session secret or fail fast in non-test envs."""
    if settings.session_secret is not None:
        val = settings.session_secret.get_secret_value()
        if len(val.encode("utf-8")) >= 32:
            return val
    if settings.app_env == "test":
        return "test_session_secret_01234567890123456789"
    raise RuntimeError("SESSION_SECRET must be at least 32 bytes and configured")


def set_demo_session_cookie(
    response: Response,
    *,
    cookie_value: str,
    max_age_seconds: int,
    secure: bool = False,
) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=cookie_value,
        max_age=max_age_seconds,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )


def clear_demo_session_cookie(response: Response, *, secure: bool = False) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


async def get_current_user(
    request: Request,
    memtrace_demo_session: Annotated[str | None, Cookie()] = None,
) -> UserContext:
    """FastAPI dependency to authenticate demo session cookie and return UserContext."""
    settings: Settings = request.app.state.settings
    secret = get_session_secret(settings)

    if not memtrace_demo_session:
        raise ApiError(
            status_code=401,
            code=ErrorCode.SESSION_REQUIRED,
            message="需要有效的 Demo 会话，请先建立会话。",
        )

    raw_token = verify_cookie_value(memtrace_demo_session, secret)
    if raw_token is None:
        raise ApiError(
            status_code=401,
            code=ErrorCode.SESSION_REQUIRED,
            message="需要有效的 Demo 会话，请先建立会话。",
        )

    token_h = hash_token(raw_token)
    session_factory = request.app.state.db_session_factory
    with session_scope(session_factory) as session:
        session_repo = SessionRepository(session)
        res = session_repo.get_valid_session_user(token_h)
        if res is None:
            raise ApiError(
                status_code=401,
                code=ErrorCode.SESSION_REQUIRED,
                message="需要有效的 Demo 会话，请先建立会话。",
            )
        _, user = res
        return UserContext(user_id=user.id, demo_alias=user.demo_alias)
