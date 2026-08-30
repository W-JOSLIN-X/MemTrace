"""Day 7 local public-account authentication, rate limits, and quotas."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import and_, delete, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from memtrace_api.config import Settings
from memtrace_api.database import session_scope
from memtrace_api.db_models import (
    AccountRecoveryCredentialModel,
    AuthRateLimitBucketModel,
    DailyTurnQuotaModel,
    DemoSessionModel,
    LocalAccountModel,
    RegistrationInviteModel,
    UserModel,
)
from memtrace_api.errors import ApiError, ErrorCode, ErrorEnvelope
from memtrace_api.idempotency import compute_request_hash, validate_idempotency_key
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.release_schemas import (
    AccountPreferencesRequest,
    AccountProjection,
    AuthActionResponse,
    AuthSessionResponse,
    ChangePasswordRequest,
    DeleteAccountRequest,
    LoginRequest,
    QuotaProjection,
    RecoverRequest,
    RecoveryCodeResponse,
    RecoveryResponse,
    RegisterRequest,
    RegisterResponse,
)
from memtrace_api.repositories import IdempotencyRepository, UserContext
from memtrace_api.schemas import EffectiveMemoryMode, ProviderMode, utc_now
from memtrace_api.session_auth import (
    clear_public_session_cookie,
    derive_csrf_token,
    get_current_user,
    get_session_secret,
    hash_token,
    set_public_session_cookie,
    sign_cookie_value,
)

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("MemTrace-dummy-password-never-valid-2026")
_LOGIN_WINDOW = timedelta(minutes=15)
_PUBLIC_WRITE_WINDOW = timedelta(hours=1)
_LOGIN_LIMIT = 5
_PUBLIC_WRITE_LIMIT = 5
_AUTH_IDEMPOTENCY_TTL = timedelta(hours=48)

router = APIRouter(prefix="/api/v2/auth", tags=["public-auth"])


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity_hash(secret: str, action: str, value: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), f"{action}:{value}".encode(), hashlib.sha256
    ).hexdigest()


def _client_ip(request: Request) -> str:
    # Forwarded headers are intentionally ignored until deployment explicitly
    # configures and documents a trusted proxy boundary.
    return request.client.host if request.client is not None else "unknown"


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _consume_rate_limits(
    factory: sessionmaker[Session],
    settings: Settings,
    *,
    action: str,
    identities: list[str],
    limit: int,
    window: timedelta,
) -> int | None:
    """Atomically consume attempts; return retry seconds when already blocked."""

    now = utc_now()
    secret = get_session_secret(settings)
    retry_after = 0
    with session_scope(factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        for identity in identities:
            digest = _identity_hash(secret, action, identity)
            row = session.execute(
                select(AuthRateLimitBucketModel).where(
                    and_(
                        AuthRateLimitBucketModel.action == action,
                        AuthRateLimitBucketModel.identity_hash == digest,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = AuthRateLimitBucketModel(
                    id=new_prefixed_ulid("rate"),
                    action=action,
                    identity_hash=digest,
                    window_started_at=now,
                    attempt_count=0,
                    blocked_until=None,
                    updated_at=now,
                )
                session.add(row)
                session.flush([row])
            started = _as_utc(row.window_started_at)
            if now >= started + window:
                row.window_started_at = now
                row.attempt_count = 0
                row.blocked_until = None
            if row.blocked_until is not None and now < _as_utc(row.blocked_until):
                retry_after = max(
                    retry_after, int((_as_utc(row.blocked_until) - now).total_seconds()) + 1
                )
                continue
            if row.attempt_count >= limit:
                row.blocked_until = _as_utc(row.window_started_at) + window
                retry_after = max(
                    retry_after, int((_as_utc(row.blocked_until) - now).total_seconds()) + 1
                )
                continue
            row.attempt_count += 1
            row.updated_at = now
    return retry_after or None


def _clear_rate_limits(
    factory: sessionmaker[Session], settings: Settings, *, action: str, identities: list[str]
) -> None:
    secret = get_session_secret(settings)
    hashes = [_identity_hash(secret, action, item) for item in identities]
    with session_scope(factory) as session:
        session.execute(
            delete(AuthRateLimitBucketModel).where(
                and_(
                    AuthRateLimitBucketModel.action == action,
                    AuthRateLimitBucketModel.identity_hash.in_(hashes),
                )
            )
        )


def _enforce_rate_limit(retry_after: int | None) -> None:
    if retry_after is not None:
        raise ApiError(
            status_code=429,
            code=ErrorCode.RATE_LIMITED,
            message="尝试次数过多，请稍后再试。",
            retryable=True,
            details={"retry_after_seconds": retry_after},
        )


def _new_recovery_code() -> str:
    return "rec_" + secrets.token_urlsafe(32)


def _new_public_session(
    session: Session,
    settings: Settings,
    *,
    owner_id: str,
) -> tuple[str, str, datetime]:
    raw_token = secrets.token_urlsafe(32)
    secret = get_session_secret(settings)
    csrf_token = derive_csrf_token(raw_token, secret)
    expires_at = utc_now() + timedelta(hours=settings.public_session_hours)
    session.add(
        DemoSessionModel(
            id=new_prefixed_ulid("sess"),
            owner_id=owner_id,
            token_hash=hash_token(raw_token),
            expires_at=expires_at,
            revoked_at=None,
            csrf_token_hash=hash_token(csrf_token),
            auth_kind="public",
            revoked_reason=None,
            created_at=utc_now(),
        )
    )
    return sign_cookie_value(raw_token, secret), csrf_token, expires_at


def quota_projection(session: Session, settings: Settings, *, owner_id: str) -> QuotaProjection:
    now = utc_now()
    today = now.date().isoformat()
    row = session.get(DailyTurnQuotaModel, (owner_id, today))
    used = row.used_turns if row is not None else 0
    active = row.active_turns if row is not None else 0
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return QuotaProjection(
        limit=settings.daily_real_turn_limit,
        used=used,
        remaining=max(0, settings.daily_real_turn_limit - used),
        active=active,
        resets_at=tomorrow,
    )


def reserve_turn_quota(
    factory: sessionmaker[Session], settings: Settings, user_ctx: UserContext
) -> None:
    """Reserve one billable public turn and enforce per-owner concurrency."""

    if user_ctx.auth_kind != "public":
        return
    now = utc_now()
    today = now.date().isoformat()
    with session_scope(factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        row = session.get(DailyTurnQuotaModel, (user_ctx.user_id, today))
        if row is None:
            row = DailyTurnQuotaModel(
                owner_id=user_ctx.user_id,
                utc_date=today,
                used_turns=0,
                active_turns=0,
                updated_at=now,
            )
            session.add(row)
            session.flush([row])
        if row.used_turns >= settings.daily_real_turn_limit:
            raise ApiError(
                status_code=429,
                code=ErrorCode.QUOTA_EXHAUSTED,
                message="今日真实模型额度已用完。",
                details={"quota_remaining": 0},
            )
        if row.active_turns >= settings.max_active_turns_per_owner:
            raise ApiError(
                status_code=409,
                code=ErrorCode.CONCURRENT_TURN_LIMIT,
                message="当前账号已有一轮对话正在处理。",
                retryable=True,
            )
        row.used_turns += 1
        row.active_turns += 1
        row.updated_at = now


def finish_turn_quota(
    factory: sessionmaker[Session], settings: Settings, user_ctx: UserContext
) -> None:
    if user_ctx.auth_kind != "public":
        return
    now = utc_now()
    with session_scope(factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        row = session.get(DailyTurnQuotaModel, (user_ctx.user_id, now.date().isoformat()))
        if row is not None:
            row.active_turns = max(0, row.active_turns - 1)
            row.updated_at = now


def recover_stale_public_state(factory: sessionmaker[Session]) -> None:
    """Release process-scoped quota leases after interrupted application runs."""

    with session_scope(factory) as session:
        session.execute(
            update(DailyTurnQuotaModel)
            .where(DailyTurnQuotaModel.active_turns > 0)
            .values(active_turns=0, updated_at=utc_now())
        )


def _session_response(
    factory: sessionmaker[Session],
    settings: Settings,
    *,
    request_id: str,
    owner_id: str,
    csrf_token: str,
    expires_at: datetime,
) -> AuthSessionResponse:
    with session_scope(factory) as session:
        account = session.get(LocalAccountModel, owner_id)
        if account is None or account.status != "active":
            raise ApiError(
                status_code=401,
                code=ErrorCode.SESSION_REQUIRED,
                message="需要有效会话，请先登录。",
            )
        quota = quota_projection(session, settings, owner_id=owner_id)
        return AuthSessionResponse(
            request_id=request_id,
            account=AccountProjection(
                username=account.username_normalized,
                display_name=account.display_name,
                status="active",
                default_memory_mode=EffectiveMemoryMode(account.default_memory_mode),
            ),
            csrf_token=csrf_token,
            session_expires_at=expires_at,
            quota=quota,
            provider_mode=ProviderMode(settings.provider_mode),
            model=settings.llm_model,
            key_configured=settings.has_llm_api_key,
        )


def _require_public(user_ctx: UserContext) -> None:
    if user_ctx.auth_kind != "public" or user_ctx.username is None:
        raise ApiError(
            status_code=401,
            code=ErrorCode.ACCOUNT_REQUIRED,
            message="该接口需要公开账号会话。",
        )


def _authenticated_request_hash(
    request: Request,
    body: dict[str, Any] | None,
) -> str:
    """Hash an authenticated mutation without persisting its sensitive body."""

    return compute_request_hash(
        method=request.method,
        path=request.url.path,
        body=body or {},
    )


def _load_idempotent_response(
    session: Session,
    user_ctx: UserContext,
    *,
    route: str,
    key: str,
    request_hash: str,
) -> dict[str, Any] | None:
    record = IdempotencyRepository(user_ctx, session).get_record(route, key)
    if record is None:
        return None
    if record.request_hash != request_hash:
        raise ApiError(
            status_code=409,
            code=ErrorCode.IDEMPOTENCY_CONFLICT,
            message="Idempotency-Key 已用于不同的请求载荷。",
        )
    loaded = json.loads(record.response_json)
    if not isinstance(loaded, dict):
        raise RuntimeError("authenticated idempotency response must be an object")
    return loaded


def _save_idempotent_response(
    session: Session,
    user_ctx: UserContext,
    *,
    route: str,
    key: str,
    request_hash: str,
    response_body: dict[str, Any],
) -> None:
    IdempotencyRepository(user_ctx, session).save_record(
        route=route,
        key=key,
        request_hash=request_hash,
        response_status=200,
        response_json=json.dumps(response_body, sort_keys=True, separators=(",", ":")),
        expires_at=utc_now() + _AUTH_IDEMPOTENCY_TTL,
    )


def _deterministic_recovery_code(
    settings: Settings,
    *,
    owner_id: str,
    idempotency_key: str,
) -> str:
    """Derive a replayable one-time code without storing its plaintext in SQLite."""

    digest = hmac.new(
        get_session_secret(settings).encode("utf-8"),
        f"recovery-rotate:{owner_id}:{idempotency_key}".encode(),
        hashlib.sha256,
    ).digest()
    return "rec_" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorEnvelope}, 429: {"model": ErrorEnvelope}},
)
async def register(request: Request, response: Response, body: RegisterRequest) -> RegisterResponse:
    settings: Settings = request.app.state.settings
    factory: sessionmaker[Session] = request.app.state.db_session_factory
    identity = _client_ip(request)
    _enforce_rate_limit(
        _consume_rate_limits(
            factory,
            settings,
            action="register",
            identities=[identity],
            limit=_PUBLIC_WRITE_LIMIT,
            window=_PUBLIC_WRITE_WINDOW,
        )
    )
    password_hash = hash_password(body.password)
    invite_hash = _secret_hash(body.invitation_code)
    recovery_code = _new_recovery_code()
    now = utc_now()
    with session_scope(factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        invite = session.execute(
            select(RegistrationInviteModel).where(RegistrationInviteModel.code_hash == invite_hash)
        ).scalar_one_or_none()
        if (
            invite is None
            or invite.status != "active"
            or _as_utc(invite.expires_at) <= now
            or invite.use_count >= invite.max_uses
        ):
            raise ApiError(
                status_code=409,
                code=ErrorCode.INVITATION_INVALID,
                message="邀请码无效、已使用或已过期。",
            )
        exists = session.execute(
            select(LocalAccountModel.owner_id).where(
                LocalAccountModel.username_normalized == body.username
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise ApiError(
                status_code=409,
                code=ErrorCode.AUTHENTICATION_FAILED,
                message="无法完成注册，请更换用户名或邀请码。",
            )
        owner_id = new_prefixed_ulid("usr")
        session.add(
            UserModel(
                id=owner_id,
                demo_alias=f"account_{owner_id}",
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            LocalAccountModel(
                owner_id=owner_id,
                username_normalized=body.username,
                display_name=body.display_name,
                password_hash=password_hash,
                status="active",
                default_memory_mode="on",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            AccountRecoveryCredentialModel(
                owner_id=owner_id,
                code_hash=_secret_hash(recovery_code),
                rotated_at=now,
                created_at=now,
            )
        )
        invite.use_count += 1
        invite.updated_at = now
        if invite.use_count >= invite.max_uses:
            invite.status = "exhausted"
        cookie_value, csrf_token, expires_at = _new_public_session(
            session, settings, owner_id=owner_id
        )
    set_public_session_cookie(
        response,
        cookie_value=cookie_value,
        max_age_seconds=settings.public_session_hours * 3600,
        secure=settings.cookie_secure,
    )
    auth_session = _session_response(
        factory,
        settings,
        request_id=request.state.request_id,
        owner_id=owner_id,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )
    return RegisterResponse(
        request_id=request.state.request_id,
        session=auth_session,
        recovery_code=recovery_code,
    )


@router.post(
    "/login",
    response_model=AuthSessionResponse,
    responses={401: {"model": ErrorEnvelope}, 429: {"model": ErrorEnvelope}},
)
async def login(request: Request, response: Response, body: LoginRequest) -> AuthSessionResponse:
    settings: Settings = request.app.state.settings
    factory: sessionmaker[Session] = request.app.state.db_session_factory
    identities = [f"username:{body.username}", f"ip:{_client_ip(request)}"]
    _enforce_rate_limit(
        _consume_rate_limits(
            factory,
            settings,
            action="login",
            identities=identities,
            limit=_LOGIN_LIMIT,
            window=_LOGIN_WINDOW,
        )
    )
    with session_scope(factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        account = session.execute(
            select(LocalAccountModel).where(LocalAccountModel.username_normalized == body.username)
        ).scalar_one_or_none()
        candidate_hash = account.password_hash if account is not None else _DUMMY_PASSWORD_HASH
        password_ok = verify_password(candidate_hash, body.password)
        if account is None or account.status != "active" or not password_ok:
            raise ApiError(
                status_code=401,
                code=ErrorCode.AUTHENTICATION_FAILED,
                message="用户名或密码不正确。",
            )
        if PASSWORD_HASHER.check_needs_rehash(account.password_hash):
            account.password_hash = hash_password(body.password)
            account.updated_at = utc_now()
        cookie_value, csrf_token, expires_at = _new_public_session(
            session, settings, owner_id=account.owner_id
        )
        owner_id = account.owner_id
    _clear_rate_limits(factory, settings, action="login", identities=identities)
    set_public_session_cookie(
        response,
        cookie_value=cookie_value,
        max_age_seconds=settings.public_session_hours * 3600,
        secure=settings.cookie_secure,
    )
    return _session_response(
        factory,
        settings,
        request_id=request.state.request_id,
        owner_id=owner_id,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )


@router.get(
    "/session",
    response_model=AuthSessionResponse,
    responses={401: {"model": ErrorEnvelope}},
)
async def session_info(
    request: Request, user_ctx: UserContext = Depends(get_current_user)
) -> AuthSessionResponse:
    _require_public(user_ctx)
    if (
        user_ctx.csrf_token is None
        or user_ctx.session_expires_at is None
        or user_ctx.session_id is None
    ):
        raise ApiError(
            status_code=401,
            code=ErrorCode.SESSION_REQUIRED,
            message="需要有效会话，请先登录。",
        )
    return _session_response(
        request.app.state.db_session_factory,
        request.app.state.settings,
        request_id=request.state.request_id,
        owner_id=user_ctx.user_id,
        csrf_token=user_ctx.csrf_token,
        expires_at=user_ctx.session_expires_at,
    )


@router.post("/logout", response_model=AuthActionResponse)
async def logout(
    request: Request,
    response: Response,
    user_ctx: UserContext = Depends(get_current_user),
    idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AuthActionResponse:
    _require_public(user_ctx)
    idempotency_key = validate_idempotency_key(idempotency_key_raw)
    route = request.url.path
    request_hash = _authenticated_request_hash(request, None)
    with session_scope(request.app.state.db_session_factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        replay = _load_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            result = AuthActionResponse.model_validate(replay)
            clear_public_session_cookie(response, secure=request.app.state.settings.cookie_secure)
            return result
        session.execute(
            update(DemoSessionModel)
            .where(
                and_(
                    DemoSessionModel.id == user_ctx.session_id,
                    DemoSessionModel.owner_id == user_ctx.user_id,
                    DemoSessionModel.auth_kind == "public",
                    DemoSessionModel.revoked_at.is_(None),
                )
            )
            .values(revoked_at=utc_now(), revoked_reason="logout")
        )
        result = AuthActionResponse(request_id=request.state.request_id, status="logged_out")
        _save_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
            response_body=result.model_dump(mode="json"),
        )
    clear_public_session_cookie(response, secure=request.app.state.settings.cookie_secure)
    return result


@router.post("/logout-all", response_model=AuthActionResponse)
async def logout_all(
    request: Request,
    response: Response,
    user_ctx: UserContext = Depends(get_current_user),
    idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AuthActionResponse:
    _require_public(user_ctx)
    idempotency_key = validate_idempotency_key(idempotency_key_raw)
    route = request.url.path
    request_hash = _authenticated_request_hash(request, None)
    with session_scope(request.app.state.db_session_factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        replay = _load_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            result = AuthActionResponse.model_validate(replay)
            clear_public_session_cookie(response, secure=request.app.state.settings.cookie_secure)
            return result
        session.execute(
            update(DemoSessionModel)
            .where(
                and_(
                    DemoSessionModel.owner_id == user_ctx.user_id,
                    DemoSessionModel.auth_kind == "public",
                    DemoSessionModel.revoked_at.is_(None),
                )
            )
            .values(revoked_at=utc_now(), revoked_reason="logout_all")
        )
        result = AuthActionResponse(
            request_id=request.state.request_id,
            status="all_sessions_revoked",
        )
        _save_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
            response_body=result.model_dump(mode="json"),
        )
    clear_public_session_cookie(response, secure=request.app.state.settings.cookie_secure)
    return result


@router.post("/change-password", response_model=AuthActionResponse)
async def change_password(
    request: Request,
    response: Response,
    body: ChangePasswordRequest,
    user_ctx: UserContext = Depends(get_current_user),
    idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AuthActionResponse:
    _require_public(user_ctx)
    idempotency_key = validate_idempotency_key(idempotency_key_raw)
    route = request.url.path
    request_hash = _authenticated_request_hash(request, body.model_dump(mode="json"))
    with session_scope(request.app.state.db_session_factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        replay = _load_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            result = AuthActionResponse.model_validate(replay)
            clear_public_session_cookie(response, secure=request.app.state.settings.cookie_secure)
            return result
        account = session.get(LocalAccountModel, user_ctx.user_id)
        if account is None or not verify_password(account.password_hash, body.current_password):
            raise ApiError(
                status_code=401,
                code=ErrorCode.AUTHENTICATION_FAILED,
                message="当前密码不正确。",
            )
        account.password_hash = hash_password(body.new_password)
        account.updated_at = utc_now()
        session.execute(
            update(DemoSessionModel)
            .where(
                and_(
                    DemoSessionModel.owner_id == user_ctx.user_id,
                    DemoSessionModel.auth_kind == "public",
                    DemoSessionModel.revoked_at.is_(None),
                )
            )
            .values(revoked_at=utc_now(), revoked_reason="password_changed")
        )
        result = AuthActionResponse(
            request_id=request.state.request_id,
            status="password_changed",
        )
        _save_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
            response_body=result.model_dump(mode="json"),
        )
    clear_public_session_cookie(response, secure=request.app.state.settings.cookie_secure)
    return result


@router.post(
    "/recover",
    response_model=RecoveryResponse,
    responses={400: {"model": ErrorEnvelope}, 429: {"model": ErrorEnvelope}},
)
async def recover(request: Request, body: RecoverRequest) -> RecoveryResponse:
    settings: Settings = request.app.state.settings
    factory: sessionmaker[Session] = request.app.state.db_session_factory
    identity = _client_ip(request)
    _enforce_rate_limit(
        _consume_rate_limits(
            factory,
            settings,
            action="recover",
            identities=[identity],
            limit=_PUBLIC_WRITE_LIMIT,
            window=_PUBLIC_WRITE_WINDOW,
        )
    )
    new_hash = hash_password(body.new_password)
    next_recovery = _new_recovery_code()
    with session_scope(factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        account = session.execute(
            select(LocalAccountModel).where(LocalAccountModel.username_normalized == body.username)
        ).scalar_one_or_none()
        credential = (
            session.get(AccountRecoveryCredentialModel, account.owner_id)
            if account is not None
            else None
        )
        valid = (
            account is not None
            and account.status == "active"
            and credential is not None
            and hmac.compare_digest(credential.code_hash, _secret_hash(body.recovery_code))
        )
        if not valid or account is None or credential is None:
            raise ApiError(
                status_code=400,
                code=ErrorCode.RECOVERY_FAILED,
                message="无法使用所提供的信息恢复账号。",
            )
        account.password_hash = new_hash
        account.updated_at = utc_now()
        credential.code_hash = _secret_hash(next_recovery)
        credential.rotated_at = utc_now()
        result = session.execute(
            update(DemoSessionModel)
            .where(
                and_(
                    DemoSessionModel.owner_id == account.owner_id,
                    DemoSessionModel.auth_kind == "public",
                    DemoSessionModel.revoked_at.is_(None),
                )
            )
            .values(revoked_at=utc_now(), revoked_reason="recovered")
        )
        revoked = result.rowcount or 0
    return RecoveryResponse(
        request_id=request.state.request_id,
        recovery_code=next_recovery,
        sessions_revoked=revoked,
    )


@router.post("/recovery-code/rotate", response_model=RecoveryCodeResponse)
async def rotate_recovery_code(
    request: Request,
    user_ctx: UserContext = Depends(get_current_user),
    idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RecoveryCodeResponse:
    _require_public(user_ctx)
    idempotency_key = validate_idempotency_key(idempotency_key_raw)
    route = request.url.path
    request_hash = _authenticated_request_hash(request, None)
    recovery_code = _deterministic_recovery_code(
        request.app.state.settings,
        owner_id=user_ctx.user_id,
        idempotency_key=idempotency_key,
    )
    with session_scope(request.app.state.db_session_factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        replay = _load_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return RecoveryCodeResponse(
                request_id=str(replay["request_id"]),
                recovery_code=recovery_code,
            )
        credential = session.get(AccountRecoveryCredentialModel, user_ctx.user_id)
        if credential is None:
            credential = AccountRecoveryCredentialModel(
                owner_id=user_ctx.user_id,
                code_hash=_secret_hash(recovery_code),
                rotated_at=utc_now(),
                created_at=utc_now(),
            )
            session.add(credential)
        else:
            credential.code_hash = _secret_hash(recovery_code)
            credential.rotated_at = utc_now()
        _save_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
            response_body={"request_id": request.state.request_id, "completed": True},
        )
    return RecoveryCodeResponse(
        request_id=request.state.request_id,
        recovery_code=recovery_code,
    )


@router.patch("/account/preferences", response_model=AuthActionResponse)
async def update_preferences(
    request: Request,
    body: AccountPreferencesRequest,
    user_ctx: UserContext = Depends(get_current_user),
    idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AuthActionResponse:
    _require_public(user_ctx)
    idempotency_key = validate_idempotency_key(idempotency_key_raw)
    route = request.url.path
    request_hash = _authenticated_request_hash(request, body.model_dump(mode="json"))
    with session_scope(request.app.state.db_session_factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        replay = _load_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return AuthActionResponse.model_validate(replay)
        account = session.get(LocalAccountModel, user_ctx.user_id)
        if account is None:
            raise ApiError(
                status_code=404,
                code=ErrorCode.ACCOUNT_REQUIRED,
                message="账号不存在。",
            )
        account.default_memory_mode = body.default_memory_mode.value
        account.updated_at = utc_now()
        result = AuthActionResponse(
            request_id=request.state.request_id,
            status="preferences_updated",
        )
        _save_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
            response_body=result.model_dump(mode="json"),
        )
    return result


@router.delete("/account", response_model=AuthActionResponse)
async def delete_account(
    request: Request,
    response: Response,
    body: DeleteAccountRequest,
    user_ctx: UserContext = Depends(get_current_user),
    idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AuthActionResponse:
    _require_public(user_ctx)
    idempotency_key = validate_idempotency_key(idempotency_key_raw)
    route = request.url.path
    request_hash = _authenticated_request_hash(request, body.model_dump(mode="json"))
    with session_scope(request.app.state.db_session_factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        replay = _load_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            result = AuthActionResponse.model_validate(replay)
            clear_public_session_cookie(response, secure=request.app.state.settings.cookie_secure)
            return result
        account = session.get(LocalAccountModel, user_ctx.user_id)
        if (
            account is None
            or body.confirm_username != account.username_normalized
            or not verify_password(account.password_hash, body.current_password)
        ):
            raise ApiError(
                status_code=409,
                code=ErrorCode.ACCOUNT_CONFIRMATION_MISMATCH,
                message="账号删除确认信息不匹配。",
            )
        result = AuthActionResponse(
            request_id=request.state.request_id,
            status="account_deleted",
        )
        _save_idempotent_response(
            session,
            user_ctx,
            route=route,
            key=idempotency_key,
            request_hash=request_hash,
            response_body=result.model_dump(mode="json"),
        )
        session.execute(delete(UserModel).where(UserModel.id == user_ctx.user_id))
    clear_public_session_cookie(response, secure=request.app.state.settings.cookie_secure)
    return result
