"""Demo session authentication, HMAC signing, and UserContext dependency."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, timedelta

from fastapi import Request, Response
from sqlalchemy import select

from memtrace_api.config import Settings
from memtrace_api.database import session_scope
from memtrace_api.db_models import LocalAccountModel
from memtrace_api.errors import ApiError, ErrorCode
from memtrace_api.repositories import SessionRepository, UserContext

COOKIE_NAME = "memtrace_demo_session"
PUBLIC_COOKIE_NAME = "memtrace_session"
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


def derive_csrf_token(raw_token: str, secret: str) -> str:
    """Derive a session-bound CSRF token without storing its plaintext."""

    digest = hmac.new(secret.encode("utf-8"), f"csrf:{raw_token}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


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


def set_public_session_cookie(
    response: Response,
    *,
    cookie_value: str,
    max_age_seconds: int,
    secure: bool,
) -> None:
    response.set_cookie(
        key=PUBLIC_COOKIE_NAME,
        value=cookie_value,
        max_age=max_age_seconds,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )


def clear_public_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=PUBLIC_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


async def get_current_user(
    request: Request,
) -> UserContext:
    """Authenticate a public or explicitly enabled compatibility session."""
    settings: Settings = request.app.state.settings
    secret = get_session_secret(settings)
    public_cookie = request.cookies.get(PUBLIC_COOKIE_NAME)
    demo_cookie = request.cookies.get(COOKIE_NAME)
    cookie_value = public_cookie or demo_cookie
    expected_kind = "public" if public_cookie else "demo"

    if not cookie_value:
        raise ApiError(
            status_code=401,
            code=ErrorCode.SESSION_REQUIRED,
            message="需要有效会话，请先登录。",
        )

    if expected_kind == "demo" and not settings.allow_demo_sessions:
        raise ApiError(
            status_code=401,
            code=ErrorCode.SESSION_REQUIRED,
            message="需要有效会话，请先登录。",
        )

    raw_token = verify_cookie_value(cookie_value, secret)
    if raw_token is None:
        raise ApiError(
            status_code=401,
            code=ErrorCode.SESSION_REQUIRED,
            message="需要有效会话，请先登录。",
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
                message="需要有效会话，请先登录。",
            )
        session_row, user = res
        if session_row.auth_kind != expected_kind:
            raise ApiError(
                status_code=401,
                code=ErrorCode.SESSION_REQUIRED,
                message="需要有效会话，请先登录。",
            )
        expires_at = session_row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expected_kind == "public":
            account = session.execute(
                select(LocalAccountModel).where(LocalAccountModel.owner_id == user.id)
            ).scalar_one_or_none()
            if account is None or account.status != "active":
                raise ApiError(
                    status_code=401,
                    code=ErrorCode.SESSION_REQUIRED,
                    message="需要有效会话，请先登录。",
                )
            csrf_token = derive_csrf_token(raw_token, secret)
            if session_row.csrf_token_hash != hash_token(csrf_token):
                raise ApiError(
                    status_code=401,
                    code=ErrorCode.SESSION_REQUIRED,
                    message="需要有效会话，请先登录。",
                )
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = (request.headers.get("Origin") or "").rstrip("/")
                if origin != settings.public_origin.rstrip("/"):
                    raise ApiError(
                        status_code=403,
                        code=ErrorCode.ORIGIN_INVALID,
                        message="请求来源未通过安全校验。",
                    )
                supplied_csrf = request.headers.get("X-CSRF-Token") or ""
                if not hmac.compare_digest(supplied_csrf, csrf_token):
                    raise ApiError(
                        status_code=403,
                        code=ErrorCode.CSRF_INVALID,
                        message="CSRF 校验失败，请刷新会话后重试。",
                    )
            return UserContext(
                user_id=user.id,
                demo_alias=user.demo_alias,
                session_id=session_row.id,
                session_expires_at=expires_at,
                auth_kind="public",
                username=account.username_normalized,
                display_name=account.display_name,
                csrf_token=csrf_token,
            )
        return UserContext(
            user_id=user.id,
            demo_alias=user.demo_alias,
            session_id=session_row.id,
            session_expires_at=expires_at,
            auth_kind="demo",
        )
