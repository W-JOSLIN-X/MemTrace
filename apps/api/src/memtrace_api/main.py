"""FastAPI application factory and G1 REST/SSE routes."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import inspect
import json
import logging
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Cookie, Depends, FastAPI, Header, Path, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from memtrace_api.compiler import StructuredProvider
from memtrace_api.config import Settings, get_settings
from memtrace_api.database import create_db_engine, create_session_factory, session_scope
from memtrace_api.db_models import (
    EventLogModel,
    FeedbackEventModel,
    ImportBatchModel,
    MemoryCardModel,
    MemoryEvidenceModel,
    MemoryJobModel,
    MemoryRelationModel,
    MemoryVersionModel,
    MessageModel,
    TaskFingerprintModel,
)
from memtrace_api.errors import (
    ApiError,
    ErrorCode,
    ErrorDetails,
    ErrorEnvelope,
    install_exception_handlers,
)
from memtrace_api.events import (
    EventType,
    MemoryAdmissionResolvedPayload,
    make_event,
    serialize_sse,
)
from memtrace_api.g3_service import (
    load_task_g3,
    recover_verification_jobs,
    usage_projection,
)
from memtrace_api.gates import run_all_gates
from memtrace_api.idempotency import compute_request_hash, validate_idempotency_key
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.logging_config import configure_logging
from memtrace_api.logic import analyze_task
from memtrace_api.middleware import RequestIdMiddleware
from memtrace_api.orchestrator import AgentOrchestrator
from memtrace_api.pack_service import PackValidationError, analyze_pack
from memtrace_api.providers import DeepSeekProvider, MockProvider, StreamingProvider
from memtrace_api.readiness import (
    DatabaseRevisionError,
    ensure_database_current,
    ensure_directory_writable,
)
from memtrace_api.repositories import (
    ConflictRepository,
    FeedbackRepository,
    IdempotencyRepository,
    ImportBatchRepository,
    MemoryCardG4Repository,
    MemoryJobRepository,
    MemoryMergeRepository,
    MemoryRelationRepository,
    MemoryUsageRepository,
    PackRepository,
    SessionRepository,
    TaskRepository,
    UserContext,
    UserRepository,
)
from memtrace_api.schemas import (
    ActiveMemoryEditRequest,
    DemoAlias,
    DemoSessionCreateRequest,
    DemoSessionResponse,
    Domain,
    FeedbackCreateAccepted,
    FeedbackCreateRequest,
    HealthResponse,
    ImportBatchResponse,
    ImportCommitRequest,
    ImportCommitResponse,
    MemoryCard,
    MemoryCardStatus,
    MemoryConflictDetailResponse,
    MemoryConflictDetectRequest,
    MemoryConflictDetectResponse,
    MemoryConflictResolveRequest,
    MemoryConflictResolveResponse,
    MemoryDeleteRequest,
    MemoryDeleteResponse,
    MemoryDetailResponse,
    MemoryEvidenceProjection,
    MemoryJobResponse,
    MemoryKind,
    MemoryListFilter,
    MemoryListResponse,
    MemoryMergeRequest,
    MemoryMergeResponse,
    MemoryPackDocument,
    MemoryRelationListResponse,
    MemoryRelationProjection,
    MemoryScope,
    MemoryStateRequest,
    MemoryUsageFeedbackRequest,
    MemoryUsageListResponse,
    MemoryUsageResponse,
    MemoryVersionDiffResponse,
    MemoryVersionListResponse,
    MemoryVersionProjection,
    MessageRole,
    PackExportRequest,
    PackPreviewItem,
    PackPreviewResponse,
    ProviderMode,
    ReadinessChecks,
    ReadyResponse,
    ResolveAction,
    ResolveRequest,
    ResolveResponse,
    RetrievalTraceResponse,
    RunStatus,
    SourceType,
    TaskCreateAccepted,
    TaskCreateRequest,
    TaskDeleteRequest,
    TaskDeleteResponse,
    TaskFingerprint,
    TaskSnapshot,
    TaskType,
    derive_feedback_type,
    utc_now,
)
from memtrace_api.session_auth import (
    SESSION_DURATION,
    clear_demo_session_cookie,
    get_current_user,
    get_session_secret,
    hash_token,
    set_demo_session_cookie,
    sign_cookie_value,
    verify_cookie_value,
)
from memtrace_api.store import (
    ReplayCapacityError,
    Subscription,
    SubscriptionCapacityError,
    TaskCapacityError,
    TaskMissingError,
    TaskRecord,
    TaskStore,
)
from memtrace_api.worker import MemoryJobWorker, recover_stale_jobs

API_PREFIX = "/api/v1"
TASK_ID_PATTERN = r"^task_[0-9A-HJKMNP-TV-Z]{26}$"
JOB_ID_PATTERN = r"^job_[0-9A-HJKMNP-TV-Z]{26}$"
MEMORY_ID_PATTERN = r"^mem_[0-9A-HJKMNP-TV-Z]{26}$"
MEMORY_VERSION_ID_PATTERN = r"^memver_[0-9A-HJKMNP-TV-Z]{26}$"
RELATION_ID_PATTERN = r"^rel_[0-9A-HJKMNP-TV-Z]{26}$"
BATCH_ID_PATTERN = r"^batch_[0-9A-HJKMNP-TV-Z]{26}$"
PACK_ID_PATTERN = r"^pack_[0-9A-HJKMNP-TV-Z]{26}$"
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    provider: StreamingProvider | None = None,
    memory_provider: StructuredProvider | None = None,
    store: TaskStore | None = None,
    db_session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)

    if db_session_factory is None:
        db_engine = create_db_engine(resolved_settings.memtrace_database_url)
        factory = create_session_factory(db_engine)
    else:
        factory = db_session_factory

    resolved_store = store or TaskStore(
        max_tasks=resolved_settings.max_tasks,
        max_subscribers_per_task=resolved_settings.max_subscribers_per_task,
        subscriber_queue_size=resolved_settings.subscriber_queue_size,
    )
    resolved_provider = provider or _build_available_provider(resolved_settings)
    orchestrator = (
        AgentOrchestrator(
            store=resolved_store,
            provider=resolved_provider,
            db_session_factory=factory,
        )
        if resolved_provider is not None
        else None
    )
    memory_worker = (
        MemoryJobWorker(
            factory,
            resolved_settings,
            resolved_store,
            provider=memory_provider,
        )
        if (
            resolved_settings.mock_mode
            or resolved_settings.has_llm_api_key
            or memory_provider is not None
        )
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Startup logic: ensure demo users and cleanup interrupted runs. Doing
        # this here (not at import time) keeps ``create_app`` side-effect free
        # and lets tests build an app without touching the default database.
        database_ready = False
        try:
            with session_scope(factory) as session:
                ensure_database_current(session)
                UserRepository(session).ensure_demo_users()
                raw_user_ctx = UserContext(user_id="bootstrap", demo_alias="bootstrap")
                TaskRepository(raw_user_ctx, session).cleanup_interrupted_runs()
                recover_verification_jobs(session)
            recover_stale_jobs(factory)
            database_ready = True
        except Exception as exc:
            # Liveness must remain available while readiness reports a missing
            # or stale schema. Docker migrates before starting the API.
            logger.warning("startup.database_not_ready type=%s", type(exc).__name__)
        if database_ready and memory_worker is not None:
            memory_worker.start()

        try:
            yield
        finally:
            if memory_worker is not None:
                await memory_worker.stop()
            await resolved_store.cancel_workers()
            if resolved_provider is not None:
                close = getattr(resolved_provider, "aclose", None)
                if close is not None:
                    result = close()
                    if inspect.isawaitable(result):
                        await result

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.store = resolved_store
    application.state.provider = resolved_provider
    application.state.orchestrator = orchestrator
    application.state.memory_worker = memory_worker
    application.state.db_session_factory = factory
    application.add_middleware(RequestIdMiddleware)
    install_exception_handlers(application)

    @application.get(f"{API_PREFIX}/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        current: Settings = request.app.state.settings
        return HealthResponse(
            request_id=request.state.request_id,
            version=current.app_version,
            environment=current.app_env,
            at=utc_now(),
        )

    @application.get(
        f"{API_PREFIX}/ready",
        response_model=ReadyResponse,
        responses={503: {"model": ErrorEnvelope}},
    )
    async def ready(request: Request) -> ReadyResponse:
        current: Settings = request.app.state.settings
        if not current.mock_mode and not current.has_llm_api_key:
            raise ApiError(
                status_code=503,
                code=ErrorCode.PROVIDER_CONFIG_MISSING,
                message="真实模型模式缺少 LLM_API_KEY。",
                retryable=False,
                details={"check": "provider_configuration"},
            )
        try:
            get_session_secret(current)
        except RuntimeError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="SESSION_SECRET 未按要求配置。",
                retryable=False,
                details={"check": "session_secret"},
            ) from exc
        try:
            ensure_directory_writable(current.memtrace_data_dir)
        except OSError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="运行数据目录不可写。",
                retryable=True,
                details={"check": "data_directory"},
            ) from exc

        try:
            with session_scope(request.app.state.db_session_factory) as session:
                ensure_database_current(session)
        except DatabaseRevisionError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="数据库迁移版本未达到当前唯一 head。",
                retryable=True,
                details={"check": "migration_revision"},
            ) from exc
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="数据库连接不可用。",
                retryable=True,
                details={"check": "database_connection"},
            ) from exc

        return ReadyResponse(
            request_id=request.state.request_id,
            provider_mode=ProviderMode(current.provider_mode),
            checks=ReadinessChecks(
                provider_credentials="not_required" if current.mock_mode else "pass",
                session_secret="pass",
                database="pass",
                migration_revision="pass",
            ),
            at=utc_now(),
        )

    # Demo session routes
    @application.post(
        f"{API_PREFIX}/session/demo",
        response_model=DemoSessionResponse,
        responses={422: {"model": ErrorEnvelope}},
    )
    async def create_demo_session(
        request: Request,
        response: Response,
        body: DemoSessionCreateRequest,
        memtrace_demo_session: Annotated[str | None, Cookie()] = None,
    ) -> DemoSessionResponse:
        settings: Settings = request.app.state.settings
        secret = get_session_secret(settings)
        token = secrets.token_urlsafe(32)
        token_h = hash_token(token)
        cookie_val = sign_cookie_value(token, secret)
        expires_at = utc_now() + SESSION_DURATION
        prior_token_hash: str | None = None
        if memtrace_demo_session:
            prior_token = verify_cookie_value(memtrace_demo_session, secret)
            if prior_token is not None:
                prior_token_hash = hash_token(prior_token)

        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            user_repo = UserRepository(session)
            user = user_repo.get_by_alias(body.demo_alias.value)
            if user is None:
                # bootstrap users
                users = user_repo.ensure_demo_users()
                user = users[body.demo_alias.value]
            session_repo = SessionRepository(session)
            if prior_token_hash is not None:
                session_repo.revoke_by_token_hash(prior_token_hash)
            session_repo.create_session(
                owner_id=user.id,
                token_hash=token_h,
                expires_at=expires_at,
            )

        set_demo_session_cookie(
            response,
            cookie_value=cookie_val,
            max_age_seconds=int(SESSION_DURATION.total_seconds()),
            secure=settings.cookie_secure,
        )
        return DemoSessionResponse(
            request_id=request.state.request_id,
            demo_alias=body.demo_alias,
            expires_at=expires_at,
        )

    @application.get(
        f"{API_PREFIX}/session",
        response_model=DemoSessionResponse,
        responses={401: {"model": ErrorEnvelope}},
    )
    async def get_session(
        request: Request,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> DemoSessionResponse:
        if user_ctx.session_expires_at is None:
            raise ApiError(
                status_code=401,
                code=ErrorCode.SESSION_REQUIRED,
                message="需要有效的 Demo 会话，请先建立会话。",
            )

        return DemoSessionResponse(
            request_id=request.state.request_id,
            demo_alias=DemoAlias(user_ctx.demo_alias),
            expires_at=user_ctx.session_expires_at,
        )

    @application.post(
        f"{API_PREFIX}/session/logout",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def logout(
        request: Request,
        response: Response,
        memtrace_demo_session: Annotated[str | None, Cookie()] = None,
    ) -> Response:
        settings: Settings = request.app.state.settings
        if memtrace_demo_session:
            try:
                secret = get_session_secret(settings)
                raw_token = verify_cookie_value(memtrace_demo_session, secret)
                if raw_token:
                    token_h = hash_token(raw_token)
                    session_factory = request.app.state.db_session_factory
                    with session_scope(session_factory) as session:
                        SessionRepository(session).revoke_by_token_hash(token_h)
            except Exception:
                pass

        clear_demo_session_cookie(response, secure=settings.cookie_secure)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    @application.post(
        f"{API_PREFIX}/tasks",
        response_model=TaskCreateAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            401: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope},
        },
    )
    async def create_task(
        request: Request,
        body: TaskCreateRequest,
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        current: Settings = request.app.state.settings
        current_orchestrator: AgentOrchestrator | None = request.app.state.orchestrator
        if current_orchestrator is None or (not current.mock_mode and not current.has_llm_api_key):
            raise ApiError(
                status_code=503,
                code=ErrorCode.PROVIDER_CONFIG_MISSING,
                message="真实模型模式缺少 LLM_API_KEY。",
                retryable=False,
                details={"check": "provider_configuration"},
            )

        idem_key = validate_idempotency_key(idempotency_key_raw)
        route = "POST:/api/v1/tasks"
        body_dict = body.model_dump(mode="json")
        req_hash = compute_request_hash(method="POST", path="/api/v1/tasks", body=body_dict)

        session_factory = request.app.state.db_session_factory
        # Durable replays and conflicts are resolved before scarce live capacity
        # is reserved and before classification is performed.
        with session_scope(session_factory) as session:
            existing = IdempotencyRepository(user_ctx, session).get_record(route, idem_key)
            if existing is not None:
                if existing.request_hash != req_hash:
                    raise ApiError(
                        status_code=409,
                        code=ErrorCode.IDEMPOTENCY_CONFLICT,
                        message="Idempotency-Key 冲突：同一 Key 已用于不同的请求载荷。",
                    )
                return JSONResponse(
                    status_code=existing.response_status,
                    content=json.loads(existing.response_json),
                )

        try:
            reservation = await resolved_store.reserve()
        except TaskCapacityError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="当前运行中的任务已达到容量上限。",
                retryable=True,
            ) from exc

        task_id = new_prefixed_ulid("task")
        run_id = new_prefixed_ulid("run")
        accepted_payload = TaskCreateAccepted(
            request_id=request.state.request_id,
            task_id=task_id,
            run_id=run_id,
            events_url=f"{API_PREFIX}/tasks/{task_id}/events",
            provider_mode=current_orchestrator.provider.mode,
            effective_memory_mode=body.effective_memory_mode,
        )
        record: TaskRecord | None = None
        try:
            analysis = analyze_task(body)
            with session_scope(session_factory) as session:
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise ApiError(
                            status_code=409,
                            code=ErrorCode.IDEMPOTENCY_CONFLICT,
                            message="Idempotency-Key 冲突：同一 Key 已用于不同的请求载荷。",
                        )
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )

                TaskRepository(user_ctx, session).create_task(
                    task_id=task_id,
                    run_id=run_id,
                    request=body,
                    detected_domain=analysis.fingerprint.domain,
                    provider_mode=current_orchestrator.provider.mode,
                    model=current_orchestrator.provider.model,
                )
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=202,
                    response_json=accepted_payload.model_dump_json(),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
                record = await resolved_store.create(
                    request=body,
                    analysis=analysis,
                    request_id=request.state.request_id,
                    provider_mode=current_orchestrator.provider.mode,
                    task_id=task_id,
                    run_id=run_id,
                    user_ctx=user_ctx,
                    reservation=reservation,
                )
                reservation = None
        except IntegrityError:
            if record is not None:
                await resolved_store.discard(task_id)
            return _replay_idempotent_response(
                session_factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        except TaskCapacityError as exc:
            if record is not None:
                await resolved_store.discard(task_id)
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="当前运行中的任务已达到容量上限。",
                retryable=True,
            ) from exc
        except Exception:
            if record is not None:
                await resolved_store.discard(task_id)
            raise
        finally:
            if reservation is not None:
                await resolved_store.release(reservation)

        if record is None:
            raise RuntimeError("task record was not registered")
        current_orchestrator.start(record)

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=accepted_payload.model_dump(mode="json"),
        )

    @application.get(
        f"{API_PREFIX}/tasks/{{task_id}}",
        response_model=TaskSnapshot,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
        },
    )
    async def get_task(
        request: Request,
        task_id: str = Path(pattern=TASK_ID_PATTERN),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> TaskSnapshot:
        # First check if live record in memory belongs to this owner
        live_snapshot: TaskSnapshot | None = None
        try:
            live_record = await resolved_store.get(task_id)
            if (
                live_record.user_ctx is not None
                and live_record.user_ctx.user_id != user_ctx.user_id
            ):
                raise _task_not_found(task_id)
            live_snapshot = await resolved_store.snapshot(
                task_id, request_id=request.state.request_id
            )
            if not live_record.closed and not live_record.snapshot.terminal:
                return live_snapshot
        except TaskMissingError:
            pass

        # Fallback to database snapshot
        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            task_repo = TaskRepository(user_ctx, session)
            snap = task_repo.get_snapshot(task_id, request_id=request.state.request_id)
            if snap is None:
                raise _task_not_found(task_id)
            if live_snapshot is not None:
                snap = snap.model_copy(
                    update={
                        "public_plan": live_snapshot.public_plan,
                        "tool_decision": live_snapshot.tool_decision,
                        "tool_calls": live_snapshot.tool_calls,
                    }
                )
            return snap

    @application.get(
        f"{API_PREFIX}/tasks/{{task_id}}/events",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "G0/G1 task event stream",
                "content": {
                    "text/event-stream": {
                        "schema": {"type": "string"},
                    }
                },
            },
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope},
        },
    )
    async def task_events(
        request: Request,
        task_id: str = Path(pattern=TASK_ID_PATTERN),
        after_event_seq: int | None = Query(default=None, ge=0),
        after_offset: int = Query(default=0, ge=0, le=262_144),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> StreamingResponse:
        cursor = (
            after_event_seq if after_event_seq is not None else _valid_last_event_id(last_event_id)
        )

        # Check DB first for task existence and owner isolation
        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            task_repo = TaskRepository(user_ctx, session)
            db_task = task_repo.get_task(task_id)
            if db_task is None:
                raise _task_not_found(task_id)

        try:
            subscription = await resolved_store.open_subscription(
                task_id,
                after_event_seq=cursor,
                after_offset=after_offset,
            )
            # Owner check if live
            if (
                subscription._record is not None
                and subscription._record.user_ctx is not None
                and subscription._record.user_ctx.user_id != user_ctx.user_id
            ):
                raise _task_not_found(task_id)
        except TaskMissingError:
            # Reconstruct one-shot subscription from SQLite event log
            subscription = await _db_subscription(
                session_factory=session_factory,
                user_ctx=user_ctx,
                task_id=task_id,
                after_event_seq=cursor,
            )
        except SubscriptionCapacityError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="该任务的实时订阅者已达到容量上限。",
                retryable=True,
            ) from exc

        return StreamingResponse(
            _subscription_body(subscription, resolved_settings.heartbeat_seconds),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    # Feedback routes
    @application.post(
        f"{API_PREFIX}/tasks/{{task_id}}/feedback",
        response_model=FeedbackCreateAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
        },
    )
    async def create_feedback(
        request: Request,
        task_id: str = Path(pattern=TASK_ID_PATTERN),
        body: FeedbackCreateRequest = ...,
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        route = f"POST:{API_PREFIX}/tasks/{task_id}/feedback"
        body_dict = body.model_dump(mode="json")
        req_hash = compute_request_hash(
            method="POST", path=f"/api/v1/tasks/{task_id}/feedback", body=body_dict
        )

        session_factory = request.app.state.db_session_factory
        try:
            with session_scope(session_factory) as session:
                # 1. Check idempotency
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise ApiError(
                            status_code=409,
                            code=ErrorCode.IDEMPOTENCY_CONFLICT,
                            message="Idempotency-Key 冲突：同一 Key 已用于不同的反馈内容。",
                        )
                    saved_json = json.loads(existing.response_json)
                    return JSONResponse(status_code=existing.response_status, content=saved_json)

                # 2. Check task exists and belongs to owner
                task_repo = TaskRepository(user_ctx, session)
                task = task_repo.get_task(task_id)
                if task is None:
                    raise _task_not_found(task_id)

                # 3. Check latest run is succeeded and has assistant message
                run = task_repo.get_latest_run(task_id)
                if run is None or run.status != RunStatus.SUCCEEDED.value:
                    raise ApiError(
                        status_code=409,
                        code=ErrorCode.TASK_NOT_READY_FOR_FEEDBACK,
                        message="任务尚未成功完成，无法提交反馈。",
                    )

                # Find assistant message
                assistant_msg = session.execute(
                    select(MessageModel).where(
                        and_(
                            MessageModel.task_id == task_id,
                            MessageModel.run_id == run.id,
                            MessageModel.role == MessageRole.ASSISTANT.value,
                            MessageModel.owner_id == user_ctx.user_id,
                        )
                    )
                ).scalar_one_or_none()
                if assistant_msg is None:
                    raise ApiError(
                        status_code=409,
                        code=ErrorCode.TASK_NOT_READY_FOR_FEEDBACK,
                        message="任务缺少助手回复消息，无法提交反馈。",
                    )

                # 4. Check edited_output does not match original message
                if body.edited_output is not None and body.edited_output == assistant_msg.content:
                    raise ApiError(
                        status_code=422,
                        code=ErrorCode.FEEDBACK_NO_CHANGES,
                        message="编辑后的内容与原始回复完全一致，未做任何修改。",
                    )

                # 5. Derive feedback type
                derived_type = derive_feedback_type(
                    explicit_text=body.explicit_text,
                    edited_output=body.edited_output,
                    rating=body.rating,
                    accepted=body.accepted,
                )

                feedback_id = new_prefixed_ulid("feedback")
                job_id = new_prefixed_ulid("job")
                fb_repo = FeedbackRepository(user_ctx, session)
                _, _, evt_model = fb_repo.record_feedback(
                    task_id=task_id,
                    run_id=run.id,
                    feedback_id=feedback_id,
                    job_id=job_id,
                    feedback_type=derived_type,
                    explicit_text=body.explicit_text,
                    edited_output=body.edited_output,
                    rating=body.rating,
                    accepted=body.accepted,
                )

                response_payload = FeedbackCreateAccepted(
                    request_id=request.state.request_id,
                    feedback_id=feedback_id,
                    memory_job_id=job_id,
                    feedback_type=derived_type,
                    job_status="pending",
                )

                # 6. Save idempotency record in same atomic transaction
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=202,
                    response_json=response_payload.model_dump_json(),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            # A concurrent request with the same key won the unique-constraint
            # race. Replay or 409 from the winner's now-committed record.
            return _replay_idempotent_response(
                session_factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )

        # Broadcast feedback.recorded to live store if record is present
        try:
            live_rec = await resolved_store.get(task_id)
            await resolved_store.emit_preallocated_persistent(
                live_rec,
                event_type=EventType.FEEDBACK_RECORDED,
                event_seq=evt_model.seq,
                data={
                    "feedback_id": feedback_id,
                    "memory_job_id": job_id,
                    "feedback_type": derived_type.value,
                },
            )
        except TaskMissingError:
            pass

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=response_payload.model_dump(mode="json"),
        )

    @application.get(
        f"{API_PREFIX}/memory-jobs/{{job_id}}",
        response_model=MemoryJobResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    async def get_memory_job(
        request: Request,
        job_id: str = Path(pattern=JOB_ID_PATTERN),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> MemoryJobResponse:
        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            job_repo = MemoryJobRepository(user_ctx, session)
            job = job_repo.get_memory_job(job_id)
            if job is None:
                raise ApiError(
                    status_code=404,
                    code=ErrorCode.MEMORY_NOT_FOUND,
                    message="指定的 Memory Job 不存在或无权访问。",
                )
            return _memory_job_response(
                job,
                request_id=request.state.request_id,
                candidate_ids=job_repo.list_candidate_ids(job.id),
            )

    @application.post(
        f"{API_PREFIX}/memory-jobs/{{job_id}}/retry",
        response_model=MemoryJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
        },
    )
    async def retry_memory_job(
        request: Request,
        job_id: str = Path(pattern=JOB_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/memory-jobs/{job_id}/retry"
        route = f"POST:{path}"
        req_hash = compute_request_hash(method="POST", path=path, body="")
        session_factory = request.app.state.db_session_factory
        try:
            with session_scope(session_factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )

                job_repo = MemoryJobRepository(user_ctx, session)
                job = job_repo.get_memory_job(job_id)
                if job is None:
                    raise ApiError(
                        status_code=404,
                        code=ErrorCode.MEMORY_NOT_FOUND,
                        message="指定的 Memory Job 不存在或无权访问。",
                    )
                if job.status != "failed" or not job.retryable:
                    raise ApiError(
                        status_code=409,
                        code=ErrorCode.MEMORY_JOB_NOT_RETRYABLE,
                        message="该 Memory Job 当前不可重试。",
                    )
                job.status = "pending"
                job.stage = "queued"
                job.last_error_code = None
                job.retryable = False
                job.disposition = None
                job.updated_at = utc_now()
                response_payload = _memory_job_response(
                    job,
                    request_id=request.state.request_id,
                    candidate_ids=[],
                )
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=status.HTTP_202_ACCEPTED,
                    response_json=response_payload.model_dump_json(),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            return _replay_idempotent_response(
                session_factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=response_payload.model_dump(mode="json"),
        )

    # ------------------------------------------------------------------
    # Resolve candidate memory card
    # ------------------------------------------------------------------

    @application.post(
        f"{API_PREFIX}/memory-candidates/{{memory_id}}/resolve",
        response_model=ResolveResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
        },
    )
    async def resolve_memory_candidate(
        request: Request,
        body: ResolveRequest,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/memory-candidates/{memory_id}/resolve"
        route = f"POST:{path}"
        normalized_body = body.model_dump(mode="json", exclude_none=False)
        req_hash = compute_request_hash(method="POST", path=path, body=normalized_body)
        session_factory = request.app.state.db_session_factory
        try:
            with session_scope(session_factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )

                card_repo = MemoryCardG4Repository(user_ctx, session)
                card = card_repo._get(memory_id)
                if card is None:
                    raise _memory_not_found()
                if card.status != MemoryCardStatus.CANDIDATE.value:
                    raise ApiError(
                        status_code=409,
                        code=ErrorCode.MEMORY_ALREADY_RESOLVED,
                        message="该 MemoryCard 已处理，无法重复 resolve。",
                    )
                evidence_rows = card_repo.list_evidence(memory_id)
                if not evidence_rows:
                    raise ApiError(
                        status_code=422,
                        code=ErrorCode.VALIDATION_ERROR,
                        message="候选缺少可核验的证据，不能执行 resolve。",
                    )
                evidence = evidence_rows[0]
                feedback = session.execute(
                    select(FeedbackEventModel).where(
                        and_(
                            FeedbackEventModel.id == evidence.feedback_id,
                            FeedbackEventModel.owner_id == user_ctx.user_id,
                        )
                    )
                ).scalar_one()
                fingerprint_row = session.execute(
                    select(TaskFingerprintModel).where(
                        and_(
                            TaskFingerprintModel.task_id == evidence.task_id,
                            TaskFingerprintModel.owner_id == user_ctx.user_id,
                        )
                    )
                ).scalar_one()
                fingerprint = TaskFingerprint.model_validate_json(fingerprint_row.fingerprint_json)

                values = _resolved_card_values(card, body)
                if body.action in {ResolveAction.ACCEPT, ResolveAction.EDIT_ACCEPT}:
                    _enforce_resolve_admission_guard(
                        card=card,
                        values=values,
                        evidence=evidence,
                        feedback=feedback,
                        fingerprint=fingerprint,
                    )

                old_status = MemoryCardStatus.CANDIDATE
                active = body.action in {ResolveAction.ACCEPT, ResolveAction.EDIT_ACCEPT}
                new_status = MemoryCardStatus.ACTIVE if active else MemoryCardStatus.REJECTED
                disposition = {
                    ResolveAction.ACCEPT: "candidate_created",
                    ResolveAction.EDIT_ACCEPT: "candidate_created",
                    ResolveAction.REJECT: "no_memory",
                    ResolveAction.ONE_SHOT: "episode_only",
                }[body.action]
                memory_version_id = new_prefixed_ulid("memver") if active else None
                now = utc_now()
                if active:
                    session.add(
                        MemoryVersionModel(
                            id=memory_version_id,
                            owner_id=user_ctx.user_id,
                            memory_id=memory_id,
                            version=1,
                            title=values["title"],
                            rule=values["rule"],
                            avoid=values["avoid"],
                            trigger_text=values["trigger_text"],
                            scope_json=values["scope_json"],
                            exceptions_json=values["exceptions_json"],
                            created_by_action=body.action.value,
                            created_at=now,
                        )
                    )
                changed = session.execute(
                    update(MemoryCardModel)
                    .where(
                        and_(
                            MemoryCardModel.id == memory_id,
                            MemoryCardModel.owner_id == user_ctx.user_id,
                            MemoryCardModel.status == MemoryCardStatus.CANDIDATE.value,
                        )
                    )
                    .values(
                        **values,
                        status=new_status.value,
                        rejection_reason=(
                            None
                            if active
                            else (
                                "episode_only"
                                if body.action is ResolveAction.ONE_SHOT
                                else "user_rejected"
                            )
                        ),
                        current_version_id=memory_version_id,
                        version=1 if active else 0,
                        rule_confidence=1.0 if active else None,
                        scope_confidence=1.0 if active else None,
                        valid_from=now if active else None,
                        updated_at=now,
                    )
                ).rowcount
                if changed != 1:
                    raise ApiError(
                        status_code=409,
                        code=ErrorCode.MEMORY_ALREADY_RESOLVED,
                        message="该 MemoryCard 已被其他请求处理。",
                    )

                data = MemoryAdmissionResolvedPayload(
                    memory_id=memory_id,
                    old_status=old_status,
                    new_status=new_status,
                    memory_version_id=memory_version_id,
                    disposition=disposition,
                ).model_dump(mode="json")
                task_repo = TaskRepository(user_ctx, session)
                event_seq = task_repo.allocate_next_event_seq(evidence.task_id)
                task_repo.append_event(
                    stream_type="task",
                    stream_id=evidence.task_id,
                    seq=event_seq,
                    event_type=EventType.MEMORY_ADMISSION_RESOLVED.value,
                    metadata=data,
                )
                session.flush()
                session.expire_all()
                resolved_card = card_repo.get_candidate(memory_id)
                assert resolved_card is not None
                response_payload = ResolveResponse(
                    request_id=request.state.request_id,
                    memory_id=memory_id,
                    action=body.action,
                    old_status=old_status,
                    new_status=new_status,
                    disposition=disposition,
                    memory_version_id=memory_version_id,
                    card=_card_projection(resolved_card),
                )
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=response_payload.model_dump_json(),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
                event_task_id = evidence.task_id
        except IntegrityError:
            return _replay_idempotent_response(
                session_factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )

        await _broadcast_persisted_event(
            resolved_store,
            user_ctx,
            task_id=event_task_id,
            event_type=EventType.MEMORY_ADMISSION_RESOLVED,
            event_seq=event_seq,
            data=data,
        )
        return JSONResponse(content=response_payload.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Memory list & detail (read-only)
    # ------------------------------------------------------------------

    @application.get(
        f"{API_PREFIX}/memories",
        response_model=MemoryListResponse,
        responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    )
    async def list_memories(
        request: Request,
        query: str | None = Query(default=None, min_length=1, max_length=100),
        kind: Annotated[MemoryKind | None, Query()] = None,
        status: Annotated[MemoryCardStatus | None, Query()] = None,
        domain: Annotated[Domain | None, Query()] = None,
        task_type: Annotated[TaskType | None, Query()] = None,
        source_type: Annotated[SourceType | None, Query()] = None,
        used_after: Annotated[datetime | None, Query()] = None,
        sort: Annotated[
            Literal["updated_desc", "created_desc", "last_used_desc", "title_asc"], Query()
        ] = "updated_desc",
        cursor: Annotated[str | None, Query(max_length=1024)] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> MemoryListResponse:
        filters = MemoryListFilter(
            query=query,
            kind=kind,
            status=status,
            domain=domain,
            task_type=task_type,
            source_type=source_type,
            used_after=used_after,
            sort=sort,
            cursor=cursor,
        )
        if status is MemoryCardStatus.DELETED:
            raise ApiError(
                status_code=422,
                code=ErrorCode.VALIDATION_ERROR,
                message="deleted tombstone 不属于公开 Memory Center 查询范围。",
            )
        cursor_value, cursor_id = _decode_memory_cursor(filters)
        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            card_repo = MemoryCardG4Repository(user_ctx, session)
            cards = card_repo.list_memories(
                query=query,
                kind=kind,
                status=status,
                domain=domain,
                task_type=task_type,
                source_type=source_type,
                used_after=used_after,
                sort=sort,
                cursor_value=cursor_value,
                cursor_id=cursor_id,
                limit=51,
            )
            page = cards[:50]
            return MemoryListResponse(
                request_id=request.state.request_id,
                items=[_card_projection(card) for card in page],
                next_cursor=(_encode_memory_cursor(filters, page[-1]) if len(cards) > 50 else None),
            )

    @application.get(
        f"{API_PREFIX}/memories/{{memory_id}}",
        response_model=MemoryDetailResponse,
        responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    )
    async def get_memory_detail(
        request: Request,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> MemoryDetailResponse:
        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            card_repo = MemoryCardG4Repository(user_ctx, session)
            card = card_repo.get_detail(memory_id)
            if card is None:
                raise _memory_not_found()
            evidence = card_repo.list_evidence(memory_id=memory_id)
            versions = card_repo.list_versions(memory_id=memory_id)
            relations = card_repo.list_relations(memory_id=memory_id)
            return MemoryDetailResponse(
                request_id=request.state.request_id,
                card=_card_projection(card),
                evidence=[_evidence_projection(item) for item in evidence],
                versions=[_version_projection(item) for item in versions],
                relations=[
                    MemoryRelationProjection(
                        relation_id=rel.id,
                        from_memory_id=rel.from_memory_id,
                        to_memory_id=rel.to_memory_id,
                        relation_type=rel.relation_type,
                        status=rel.status,
                        resolution_action=rel.resolution_action,
                        resolution_memory_id=rel.resolution_memory_id,
                        created_at=rel.created_at,
                        resolved_at=rel.resolved_at,
                    )
                    for rel in relations
                ],
            )

    # ------------------------------------------------------------------
    # Day 4 retrieval trace, usage receipts, and active memory lifecycle
    # ------------------------------------------------------------------

    @application.get(
        f"{API_PREFIX}/tasks/{{task_id}}/retrieval-trace",
        response_model=RetrievalTraceResponse,
        responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    )
    async def get_retrieval_trace(
        request: Request,
        task_id: str = Path(pattern=TASK_ID_PATTERN),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> RetrievalTraceResponse:
        with session_scope(request.app.state.db_session_factory) as session:
            task_repo = TaskRepository(user_ctx, session)
            task = task_repo.get_task(task_id)
            run = task_repo.get_latest_run(task_id) if task is not None else None
            if task is None or run is None:
                raise _task_not_found(task_id)
            trace, _ = load_task_g3(
                session,
                user_ctx,
                request_id=request.state.request_id,
                task_id=task_id,
                run_id=run.id,
            )
            if trace is None:
                raise _task_not_found(task_id)
            return trace

    @application.get(
        f"{API_PREFIX}/tasks/{{task_id}}/memory-usages",
        response_model=MemoryUsageListResponse,
        responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    )
    async def get_task_memory_usages(
        request: Request,
        task_id: str = Path(pattern=TASK_ID_PATTERN),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> MemoryUsageListResponse:
        with session_scope(request.app.state.db_session_factory) as session:
            task_repo = TaskRepository(user_ctx, session)
            task = task_repo.get_task(task_id)
            run = task_repo.get_latest_run(task_id) if task is not None else None
            if task is None or run is None:
                raise _task_not_found(task_id)
            _, usages = load_task_g3(
                session,
                user_ctx,
                request_id=request.state.request_id,
                task_id=task_id,
                run_id=run.id,
            )
            return MemoryUsageListResponse(
                request_id=request.state.request_id,
                items=usages,
                next_cursor=None,
            )

    @application.patch(
        f"{API_PREFIX}/memories/{{memory_id}}",
        response_model=MemoryDetailResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
        },
    )
    async def edit_active_memory(
        request: Request,
        body: ActiveMemoryEditRequest,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/memories/{memory_id}"
        route = f"PATCH:{path}"
        normalized = body.model_dump(mode="json")
        req_hash = compute_request_hash(method="PATCH", path=path, body=normalized)
        factory = request.app.state.db_session_factory
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )
                card_repo = MemoryCardG4Repository(user_ctx, session)
                card = card_repo._get(memory_id)
                if card is None:
                    raise _memory_not_found()
                if card.status not in {
                    MemoryCardStatus.ACTIVE.value,
                    MemoryCardStatus.PAUSED.value,
                    MemoryCardStatus.ARCHIVED.value,
                    MemoryCardStatus.CONFLICTED.value,
                }:
                    raise _memory_state_conflict("当前 MemoryCard 状态不允许内容编辑。")
                if card.current_version_id != body.expected_current_version_id:
                    raise _memory_version_conflict()
                values = _active_edit_values(card, body)
                version_id = new_prefixed_ulid("memver")
                now = utc_now()
                session.add(
                    MemoryVersionModel(
                        id=version_id,
                        owner_id=user_ctx.user_id,
                        memory_id=memory_id,
                        version=card.version + 1,
                        title=values["title"],
                        rule=values["rule"],
                        avoid=values["avoid"],
                        trigger_text=values["trigger_text"],
                        scope_json=values["scope_json"],
                        exceptions_json=values["exceptions_json"],
                        created_by_action="edit",
                        created_at=now,
                    )
                )
                card_repo.update_card(
                    memory_id,
                    **values,
                    current_version_id=version_id,
                    version=card.version + 1,
                    updated_at=now,
                )
                session.flush()
                session.expire_all()
                updated = card_repo.get_candidate(memory_id)
                assert updated is not None
                payload = MemoryDetailResponse(
                    request_id=request.state.request_id,
                    card=_card_projection(updated),
                    evidence=[
                        _evidence_projection(row) for row in card_repo.list_evidence(memory_id)
                    ],
                    versions=[
                        _version_projection(row) for row in card_repo.list_versions(memory_id)
                    ],
                )
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=payload.model_dump_json(),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            return _replay_idempotent_response(
                factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        return JSONResponse(content=payload.model_dump(mode="json"))

    async def _change_memory_status(
        request: Request,
        body: MemoryStateRequest,
        memory_id: str,
        idem_key_raw: str | None,
        user_ctx: UserContext,
        *,
        old_statuses: frozenset[MemoryCardStatus],
        new_status: MemoryCardStatus,
        action: str,
    ) -> Response:
        idem_key = validate_idempotency_key(idem_key_raw)
        path = f"{API_PREFIX}/memories/{memory_id}/{action}"
        route = f"POST:{path}"
        normalized = body.model_dump(mode="json")
        req_hash = compute_request_hash(method="POST", path=path, body=normalized)
        factory = request.app.state.db_session_factory
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )
                card_repo = MemoryCardG4Repository(user_ctx, session)
                card = card_repo._get(memory_id)
                if card is None:
                    raise _memory_not_found()
                if card.status not in {item.value for item in old_statuses}:
                    raise _memory_state_conflict(f"MemoryCard 当前不能执行 {action}。")
                if card.current_version_id != body.expected_current_version_id:
                    raise _memory_version_conflict()
                if new_status is MemoryCardStatus.ACTIVE:
                    _enforce_active_invariants(card)
                    unresolved = session.execute(
                        select(MemoryRelationModel.id).where(
                            and_(
                                MemoryRelationModel.owner_id == user_ctx.user_id,
                                MemoryRelationModel.relation_type == "conflicts_with",
                                MemoryRelationModel.status == "unresolved",
                                or_(
                                    MemoryRelationModel.from_memory_id == memory_id,
                                    MemoryRelationModel.to_memory_id == memory_id,
                                ),
                            )
                        )
                    ).scalar_one_or_none()
                    if unresolved is not None:
                        raise _memory_state_conflict(
                            "MemoryCard 存在未解决冲突，不能恢复为 active。"
                        )
                previous_status = card.status
                card.status = new_status.value
                card.updated_at = utc_now()
                event_seq = _allocate_memory_event_seq(session, user_ctx.user_id, memory_id)
                TaskRepository(user_ctx, session).append_event(
                    stream_type="memory",
                    stream_id=memory_id,
                    seq=event_seq,
                    event_type=EventType.MEMORY_LIFECYCLE_CHANGED.value,
                    metadata={
                        "memory_id": memory_id,
                        "action": action,
                        "old_status": previous_status,
                        "new_status": new_status.value,
                        "version_id": card.current_version_id,
                    },
                )
                session.flush()
                payload = MemoryDetailResponse(
                    request_id=request.state.request_id,
                    card=_card_projection(card),
                    evidence=[
                        _evidence_projection(row) for row in card_repo.list_evidence(memory_id)
                    ],
                    versions=[
                        _version_projection(row) for row in card_repo.list_versions(memory_id)
                    ],
                )
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=payload.model_dump_json(),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            return _replay_idempotent_response(
                factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        return JSONResponse(content=payload.model_dump(mode="json"))

    @application.post(
        f"{API_PREFIX}/memories/{{memory_id}}/pause",
        response_model=MemoryDetailResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def pause_memory(
        request: Request,
        body: MemoryStateRequest,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        return await _change_memory_status(
            request,
            body,
            memory_id,
            idempotency_key_raw,
            user_ctx,
            old_statuses=frozenset({MemoryCardStatus.ACTIVE}),
            new_status=MemoryCardStatus.PAUSED,
            action="pause",
        )

    @application.post(
        f"{API_PREFIX}/memories/{{memory_id}}/resume",
        response_model=MemoryDetailResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def resume_memory(
        request: Request,
        body: MemoryStateRequest,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        return await _change_memory_status(
            request,
            body,
            memory_id,
            idempotency_key_raw,
            user_ctx,
            old_statuses=frozenset({MemoryCardStatus.PAUSED}),
            new_status=MemoryCardStatus.ACTIVE,
            action="resume",
        )

    @application.post(
        f"{API_PREFIX}/memories/{{memory_id}}/archive",
        response_model=MemoryDetailResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def archive_memory(
        request: Request,
        body: MemoryStateRequest,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        return await _change_memory_status(
            request,
            body,
            memory_id,
            idempotency_key_raw,
            user_ctx,
            old_statuses=frozenset({MemoryCardStatus.ACTIVE, MemoryCardStatus.PAUSED}),
            new_status=MemoryCardStatus.ARCHIVED,
            action="archive",
        )

    @application.post(
        f"{API_PREFIX}/memories/{{memory_id}}/restore",
        response_model=MemoryDetailResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def restore_memory(
        request: Request,
        body: MemoryStateRequest,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        return await _change_memory_status(
            request,
            body,
            memory_id,
            idempotency_key_raw,
            user_ctx,
            old_statuses=frozenset({MemoryCardStatus.ARCHIVED}),
            new_status=MemoryCardStatus.PAUSED,
            action="restore",
        )

    @application.get(
        f"{API_PREFIX}/memories/{{memory_id}}/versions",
        response_model=MemoryVersionListResponse,
        responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    )
    async def list_memory_versions(
        request: Request,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        cursor: str | None = Query(default=None),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> MemoryVersionListResponse:
        with session_scope(request.app.state.db_session_factory) as session:
            card_repo = MemoryCardG4Repository(user_ctx, session)
            if card_repo.get_candidate(memory_id) is None:
                raise _memory_not_found()
            query = select(MemoryVersionModel).where(
                and_(
                    MemoryVersionModel.owner_id == user_ctx.user_id,
                    MemoryVersionModel.memory_id == memory_id,
                )
            )
            if cursor:
                query = query.where(MemoryVersionModel.id < cursor)
            rows = list(
                session.execute(query.order_by(MemoryVersionModel.id.desc()).limit(51))
                .scalars()
                .all()
            )
            page = rows[:50]
            return MemoryVersionListResponse(
                request_id=request.state.request_id,
                items=[_version_projection(row) for row in page],
                next_cursor=page[-1].id if len(rows) > 50 else None,
            )

    @application.get(
        f"{API_PREFIX}/memories/{{memory_id}}/version-diff",
        response_model=MemoryVersionDiffResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
        },
    )
    async def get_memory_version_diff(
        request: Request,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        from_version_id: str = Query(pattern=MEMORY_VERSION_ID_PATTERN),
        to_version_id: str = Query(pattern=MEMORY_VERSION_ID_PATTERN),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> MemoryVersionDiffResponse:
        with session_scope(request.app.state.db_session_factory) as session:
            card_repo = MemoryCardG4Repository(user_ctx, session)
            if card_repo.get_detail(memory_id) is None:
                raise _memory_not_found()
            rows = list(
                session.execute(
                    select(MemoryVersionModel).where(
                        and_(
                            MemoryVersionModel.owner_id == user_ctx.user_id,
                            MemoryVersionModel.memory_id == memory_id,
                            MemoryVersionModel.id.in_([from_version_id, to_version_id]),
                        )
                    )
                ).scalars()
            )
            by_id = {row.id: row for row in rows}
            if from_version_id not in by_id or to_version_id not in by_id:
                raise _memory_not_found()
            before = by_id[from_version_id]
            after = by_id[to_version_id]
            changed_fields: list[str] = []
            for public_name, attr_name in (
                ("title", "title"),
                ("rule", "rule"),
                ("avoid", "avoid"),
                ("trigger_text", "trigger_text"),
                ("scope", "scope_json"),
                ("exceptions", "exceptions_json"),
            ):
                if getattr(before, attr_name) != getattr(after, attr_name):
                    changed_fields.append(public_name)
            return MemoryVersionDiffResponse(
                request_id=request.state.request_id,
                from_version=_version_projection(before),
                to_version=_version_projection(after),
                changed_fields=changed_fields,
            )

    @application.get(
        f"{API_PREFIX}/memories/{{memory_id}}/usages",
        response_model=MemoryUsageListResponse,
        responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    )
    async def list_memory_usages(
        request: Request,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        cursor: str | None = Query(default=None),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> MemoryUsageListResponse:
        with session_scope(request.app.state.db_session_factory) as session:
            card_repo = MemoryCardG4Repository(user_ctx, session)
            if card_repo.get_candidate(memory_id) is None:
                raise _memory_not_found()
            rows = MemoryUsageRepository(user_ctx, session).list_by_memory(
                memory_id,
                cursor=cursor,
                limit=51,
            )
            page = rows[:50]
            return MemoryUsageListResponse(
                request_id=request.state.request_id,
                items=[usage_projection(row, request_id=request.state.request_id) for row in page],
                next_cursor=page[-1].id if len(rows) > 50 else None,
            )

    @application.post(
        f"{API_PREFIX}/tasks/{{task_id}}/memory-usages/{{memory_id}}/feedback",
        response_model=MemoryUsageResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def record_memory_usage_feedback(
        request: Request,
        body: MemoryUsageFeedbackRequest,
        task_id: str = Path(pattern=TASK_ID_PATTERN),
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/tasks/{task_id}/memory-usages/{memory_id}/feedback"
        route = f"POST:{path}"
        normalized = body.model_dump(mode="json")
        req_hash = compute_request_hash(method="POST", path=path, body=normalized)
        factory = request.app.state.db_session_factory
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )
                task_repo = TaskRepository(user_ctx, session)
                task = task_repo.get_task(task_id)
                run = task_repo.get_latest_run(task_id) if task is not None else None
                if task is None or run is None:
                    raise _task_not_found(task_id)
                usage_repo = MemoryUsageRepository(user_ctx, session)
                usage = usage_repo.get_usage(task_id, run.id, memory_id)
                if usage is None:
                    raise _task_not_found(task_id)
                if not usage.injected or usage.user_effect is not None:
                    raise _memory_state_conflict("该 usage 当前不能记录效果反馈。")
                usage.user_effect = body.effect.value
                usage.updated_at = utc_now()
                card = MemoryCardG4Repository(user_ctx, session).get_candidate(memory_id)
                if card is None:
                    raise _memory_not_found()
                setattr(
                    card,
                    f"{body.effect.value}_count",
                    getattr(card, f"{body.effect.value}_count") + 1,
                )
                data = {
                    "usage_id": usage.id,
                    "memory_id": usage.memory_id,
                    "user_effect": body.effect.value,
                }
                event_seq = task_repo.allocate_next_event_seq(task_id)
                task_repo.append_event(
                    stream_type="task",
                    stream_id=task_id,
                    seq=event_seq,
                    event_type=EventType.MEMORY_USAGE_FEEDBACK_RECORDED.value,
                    metadata=data,
                )
                session.flush()
                payload = usage_projection(usage, request_id=request.state.request_id)
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=payload.model_dump_json(),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            return _replay_idempotent_response(
                factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        await _broadcast_persisted_event(
            resolved_store,
            user_ctx,
            task_id=task_id,
            event_type=EventType.MEMORY_USAGE_FEEDBACK_RECORDED,
            event_seq=event_seq,
            data=data,
        )
        return JSONResponse(content=payload.model_dump(mode="json"))

    # ── Day 5 G4 Memory Center lifecycle ──────────────────────────────────────

    @application.delete(
        f"{API_PREFIX}/memories/{{memory_id}}",
        response_model=MemoryDeleteResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def permanent_delete_memory(
        request: Request,
        body: MemoryDeleteRequest,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/memories/{memory_id}"
        route = f"DELETE:{path}"
        normalized = body.model_dump(mode="json")
        req_hash = compute_request_hash(method="DELETE", path=path, body=normalized)
        factory = request.app.state.db_session_factory
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )
                card_repo = MemoryCardG4Repository(user_ctx, session)
                card = card_repo.get_detail(memory_id)
                if card is None:
                    raise _memory_not_found()
                if card.current_version_id != body.expected_current_version_id:
                    raise _memory_version_conflict()
                if card.title != body.confirm_title:
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.CONFIRMATION_MISMATCH,
                        message="确认标题与当前 MemoryCard 标题不一致。",
                    )
                old_status = card.status
                old_version_id = card.current_version_id
                result = card_repo.permanent_delete(
                    memory_id=memory_id,
                    expected_version_id=body.expected_current_version_id,
                    confirm_title=body.confirm_title,
                )
                event_seq = _allocate_memory_event_seq(session, user_ctx.user_id, memory_id)
                task_repo = TaskRepository(user_ctx, session)
                task_repo.append_event(
                    stream_type="memory",
                    stream_id=memory_id,
                    seq=event_seq,
                    event_type=EventType.MEMORY_LIFECYCLE_CHANGED.value,
                    metadata={
                        "memory_id": memory_id,
                        "action": "permanent_delete",
                        "old_status": old_status,
                        "new_status": "deleted",
                        "version_id": old_version_id,
                    },
                )
                session.flush()
                response_data = {
                    "request_id": request.state.request_id,
                    "memory_id": memory_id,
                    "status": "deleted",
                    "deleted_at": result["deleted_at"].isoformat().replace("+00:00", "Z")
                    if isinstance(result["deleted_at"], datetime)
                    else str(result["deleted_at"]),
                }
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=json.dumps(response_data),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            return _replay_idempotent_response(
                factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        return JSONResponse(content=response_data, status_code=200)

    @application.delete(
        f"{API_PREFIX}/tasks/{{task_id}}",
        response_model=TaskDeleteResponse,
        status_code=200,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def delete_source_task(
        request: Request,
        body: TaskDeleteRequest,
        task_id: str = Path(pattern=TASK_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/tasks/{task_id}"
        route = f"DELETE:{path}"
        normalized = body.model_dump(mode="json")
        req_hash = compute_request_hash(method="DELETE", path=path, body=normalized)
        factory = request.app.state.db_session_factory
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )
                task_repo = TaskRepository(user_ctx, session)
                task = task_repo.get_task(task_id)
                if task is None:
                    raise _task_not_found(task_id)
                if body.confirm_task_id != task_id:
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.CONFIRMATION_MISMATCH,
                        message="确认的 task_id 与 URL 不匹配。",
                    )
                card_repo = MemoryCardG4Repository(user_ctx, session)
                result = card_repo.delete_source_task(task_id)
                event_seq = task_repo.allocate_next_event_seq(task_id)
                task_repo.append_event(
                    stream_type="task",
                    stream_id=task_id,
                    seq=event_seq,
                    event_type=EventType.TASK_DELETED.value,
                    metadata={
                        "task_id": task_id,
                        "memory_policy": body.memory_policy,
                        "affected_card_count": result["affected_card_count"],
                    },
                )
                session.flush()
                response_data = {
                    "request_id": request.state.request_id,
                    "task_id": task_id,
                    "status": "deleted",
                    "memory_policy": body.memory_policy,
                    "affected_card_count": result["affected_card_count"],
                }
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=json.dumps(response_data),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            return _replay_idempotent_response(
                factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        return JSONResponse(content=response_data, status_code=200)

    @application.get(
        f"{API_PREFIX}/memories/{{memory_id}}/relations",
        response_model=MemoryRelationListResponse,
        responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    )
    async def get_memory_relations(
        request: Request,
        memory_id: str = Path(pattern=MEMORY_ID_PATTERN),
        user_ctx: UserContext = Depends(get_current_user),
        cursor: str | None = Query(default=None),
    ) -> MemoryRelationListResponse:
        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            card_repo = MemoryCardG4Repository(user_ctx, session)
            if card_repo.get_detail(memory_id) is None:
                raise _memory_not_found()
            rows = MemoryRelationRepository(user_ctx, session).list_relations(
                memory_id=memory_id,
                cursor=cursor,
            )
            page = rows[:50]
            return MemoryRelationListResponse(
                request_id=request.state.request_id,
                items=[_relation_projection(rel) for rel in page],
                next_cursor=page[-1].id if len(rows) > 50 else None,
            )

    @application.get(
        f"{API_PREFIX}/memory-conflicts",
        response_model=MemoryRelationListResponse,
        responses={401: {"model": ErrorEnvelope}},
    )
    async def list_memory_conflicts(
        request: Request,
        status_filter: Literal["unresolved", "resolved"] | None = Query(
            default=None, alias="status"
        ),
        cursor: str | None = Query(default=None),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> MemoryRelationListResponse:
        with session_scope(request.app.state.db_session_factory) as session:
            rows = ConflictRepository(user_ctx, session).list_conflicts(
                status=status_filter,
                cursor=cursor,
            )
            page = rows[:50]
            return MemoryRelationListResponse(
                request_id=request.state.request_id,
                items=[_relation_projection(row) for row in page],
                next_cursor=page[-1].id if len(rows) > 50 else None,
            )

    @application.get(
        f"{API_PREFIX}/memory-conflicts/{{relation_id}}",
        response_model=MemoryConflictDetailResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    async def get_memory_conflict(
        request: Request,
        relation_id: str = Path(pattern=RELATION_ID_PATTERN),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> MemoryConflictDetailResponse:
        with session_scope(request.app.state.db_session_factory) as session:
            relation = ConflictRepository(user_ctx, session).get(relation_id)
            if relation is None:
                raise _error_response(
                    request,
                    status_code=404,
                    code=ErrorCode.MEMORY_RELATION_NOT_FOUND,
                    message="冲突关系不存在或不属于当前用户。",
                )
            card_repo = MemoryCardG4Repository(user_ctx, session)
            left = card_repo.get_detail(relation.from_memory_id)
            right = card_repo.get_detail(relation.to_memory_id)
            if left is None or right is None:
                raise _error_response(
                    request,
                    status_code=404,
                    code=ErrorCode.MEMORY_RELATION_NOT_FOUND,
                    message="冲突关系不存在或不属于当前用户。",
                )
            return MemoryConflictDetailResponse(
                request_id=request.state.request_id,
                relation=_relation_projection(relation),
                left=_card_projection(left),
                right=_card_projection(right),
            )

    @application.post(
        f"{API_PREFIX}/memory-conflicts",
        response_model=MemoryConflictDetectResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def detect_memory_conflict(
        request: Request,
        body: MemoryConflictDetectRequest,
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/memory-conflicts"
        route = f"POST:{path}"
        normalized = body.model_dump(mode="json")
        req_hash = compute_request_hash(method="POST", path=path, body=normalized)
        factory = request.app.state.db_session_factory
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )
                card_repo = MemoryCardG4Repository(user_ctx, session)
                left_card = card_repo.get_detail(body.left_memory_id)
                right_card = card_repo.get_detail(body.right_memory_id)
                if left_card is None or right_card is None:
                    raise _memory_not_found()
                if (
                    left_card.owner_id != user_ctx.user_id
                    or right_card.owner_id != user_ctx.user_id
                ):
                    raise _memory_not_found()
                if body.left_expected_current_version_id != left_card.current_version_id:
                    raise _memory_version_conflict()
                if body.right_expected_current_version_id != right_card.current_version_id:
                    raise _memory_version_conflict()
                allowed = {"active", "paused"}
                if left_card.status not in allowed or right_card.status not in allowed:
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.MEMORY_STATE_CONFLICT,
                        message="两端 memory 必须为 active 或 paused 才能创建冲突。",
                    )
                if body.left_memory_id == body.right_memory_id:
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.MEMORY_MERGE_CONFLICT,
                        message="不能对同一 memory 创建冲突。",
                    )
                left_scope = MemoryScope.model_validate_json(left_card.scope_json)
                right_scope = MemoryScope.model_validate_json(right_card.scope_json)
                if not _scope_overlap_v1(left_scope, right_scope):
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.MEMORY_MERGE_CONFLICT,
                        message="两端 scope 明确不重叠，不能创建冲突。",
                    )
                # Create canonical pair (left_memory_id < right_memory_id)
                if body.left_memory_id > body.right_memory_id:
                    left_id, right_id = body.right_memory_id, body.left_memory_id
                else:
                    left_id, right_id = body.left_memory_id, body.right_memory_id
                relation_id = new_prefixed_ulid("rel")
                conflict_repo = ConflictRepository(user_ctx, session)
                conflict_repo.create_conflict(
                    relation_id=relation_id,
                    left_memory_id=left_id,
                    right_memory_id=right_id,
                )
                # Set both cards to conflicted
                card_repo.set_status(
                    body.left_memory_id, body.left_expected_current_version_id, "conflicted"
                )
                card_repo.set_status(
                    body.right_memory_id, body.right_expected_current_version_id, "conflicted"
                )
                for memory_id in (left_id, right_id):
                    TaskRepository(user_ctx, session).append_event(
                        stream_type="memory",
                        stream_id=memory_id,
                        seq=_next_metadata_event_seq(
                            session, user_ctx.user_id, "memory", memory_id
                        ),
                        event_type=EventType.MEMORY_CONFLICT_DETECTED.value,
                        metadata={
                            "relation_id": relation_id,
                            "left_memory_id": left_id,
                            "right_memory_id": right_id,
                            "status": "unresolved",
                        },
                    )
                response_data = MemoryConflictDetectResponse(
                    request_id=request.state.request_id,
                    relation_id=relation_id,
                    left_memory_id=left_id,
                    right_memory_id=right_id,
                ).model_dump(mode="json")
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=json.dumps(response_data),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
                session.flush()
        except IntegrityError:
            return _replay_idempotent_response(
                factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        return JSONResponse(content=response_data, status_code=200)

    @application.post(
        f"{API_PREFIX}/memory-conflicts/{{relation_id}}/resolve",
        response_model=MemoryConflictResolveResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def resolve_memory_conflict(
        request: Request,
        body: MemoryConflictResolveRequest,
        relation_id: str = Path(pattern=RELATION_ID_PATTERN),
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/memory-conflicts/{relation_id}/resolve"
        route = f"POST:{path}"
        normalized = body.model_dump(mode="json")
        req_hash = compute_request_hash(method="POST", path=path, body=normalized)
        factory = request.app.state.db_session_factory
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )
                conflict_repo = ConflictRepository(user_ctx, session)
                relation = conflict_repo.get(relation_id)
                if relation is None:
                    raise _error_response(
                        request,
                        status_code=404,
                        code=ErrorCode.MEMORY_RELATION_NOT_FOUND,
                        message="冲突关系不存在或不属于当前用户。",
                    )
                if relation.status != "unresolved":
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.MEMORY_CONFLICT_ALREADY_RESOLVED,
                        message="该冲突已被解决。",
                    )
                card_repo = MemoryCardG4Repository(user_ctx, session)
                left_card = card_repo.get_detail(relation.from_memory_id)
                right_card = card_repo.get_detail(relation.to_memory_id)
                if left_card is None or right_card is None:
                    raise _memory_not_found()
                if left_card.status != "conflicted" or right_card.status != "conflicted":
                    raise _memory_state_conflict("冲突两端当前必须保持 conflicted。")
                if (
                    left_card.current_version_id != body.left_expected_current_version_id
                    or right_card.current_version_id != body.right_expected_current_version_id
                ):
                    raise _memory_version_conflict()
                resolution_memory_id: str | None = None
                if body.action == "prefer":
                    if body.preferred_memory_id not in (
                        relation.from_memory_id,
                        relation.to_memory_id,
                    ):
                        raise _error_response(
                            request,
                            status_code=409,
                            code=ErrorCode.MEMORY_MERGE_CONFLICT,
                            message="preferred_memory_id 必须是冲突两端之一。",
                        )
                    winner_id = body.preferred_memory_id
                    resolution_memory_id = winner_id
                    loser_id = (
                        relation.to_memory_id
                        if body.preferred_memory_id == relation.from_memory_id
                        else relation.from_memory_id
                    )
                    card_repo.set_status(
                        winner_id,
                        (
                            body.left_expected_current_version_id
                            if body.preferred_memory_id == relation.from_memory_id
                            else body.right_expected_current_version_id
                        ),
                        "active",
                    )
                    card_repo.set_status(
                        loser_id,
                        (
                            body.left_expected_current_version_id
                            if loser_id == relation.from_memory_id
                            else body.right_expected_current_version_id
                        ),
                        "superseded",
                    )
                    supersedes_id = new_prefixed_ulid("rel")
                    session.add(
                        MemoryRelationModel(
                            id=supersedes_id,
                            owner_id=user_ctx.user_id,
                            from_memory_id=winner_id,
                            to_memory_id=loser_id,
                            relation_type="supersedes",
                            status="resolved",
                            resolved_at=utc_now(),
                            created_at=utc_now(),
                        )
                    )
                elif body.action == "separate_scopes":
                    assert body.left_scope is not None and body.right_scope is not None
                    if _scope_overlap_v1(body.left_scope, body.right_scope):
                        raise _error_response(
                            request,
                            status_code=409,
                            code=ErrorCode.MEMORY_MERGE_CONFLICT,
                            message="新的两个 scope 仍然重叠。",
                        )
                    for card_id, scope in [
                        (
                            relation.from_memory_id,
                            body.left_scope,
                        ),
                        (
                            relation.to_memory_id,
                            body.right_scope,
                        ),
                    ]:
                        assert scope is not None
                        scope_data = scope.model_dump(mode="json")
                        scope_json = json.dumps(
                            scope_data,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        )
                        card = card_repo.get_detail(card_id)
                        if card is None:
                            raise _memory_not_found()
                        next_ver = card.version + 1
                        new_ver_id = new_prefixed_ulid("memver")
                        session.add(
                            MemoryVersionModel(
                                id=new_ver_id,
                                owner_id=user_ctx.user_id,
                                memory_id=card_id,
                                version=next_ver,
                                title=card.title,
                                rule=card.rule,
                                avoid=card.avoid,
                                trigger_text=card.trigger_text,
                                scope_json=scope_json,
                                exceptions_json=card.exceptions_json,
                                created_by_action="scope_resolution",
                                created_at=utc_now(),
                            )
                        )
                        card_repo._update(
                            card_id,
                            scope_level=scope_data["level"],
                            domain=scope_data["domain"],
                            task_type=scope_data.get("task_type"),
                            artifact_type=scope_data.get("artifact_type"),
                            audience=scope_data.get("audience"),
                            project_key=scope_data.get("project_key"),
                            scope_json=scope_json,
                            current_version_id=new_ver_id,
                            version=next_ver,
                            status="active",
                            updated_at=utc_now(),
                        )
                elif body.action == "merge":
                    if body.merged_card is None:
                        raise _error_response(
                            request,
                            status_code=409,
                            code=ErrorCode.MEMORY_MERGE_CONFLICT,
                            message="merge action 需要 merged_card。",
                        )
                    scope = body.merged_card.scope.model_dump(mode="json")
                    scope_json = json.dumps(scope, separators=(",", ":"), ensure_ascii=False)
                    exc_json = json.dumps(
                        [item.value for item in body.merged_card.exceptions],
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    merged_id = new_prefixed_ulid("mem")
                    new_ver_id = new_prefixed_ulid("memver")
                    resolution_memory_id = merged_id
                    new_card = MemoryCardModel(
                        id=merged_id,
                        owner_id=user_ctx.user_id,
                        status="active",
                        kind=body.merged_card.kind,
                        source_type="accept",
                        save_preselected=False,
                        title=body.merged_card.title,
                        rule=body.merged_card.rule,
                        avoid=body.merged_card.avoid or "",
                        trigger_text=body.merged_card.trigger_text or "",
                        scope_level=scope.get("level", "global"),
                        domain=scope.get("domain", "other"),
                        task_type=scope.get("task_type"),
                        artifact_type=scope.get("artifact_type"),
                        audience=scope.get("audience"),
                        project_key=scope.get("project_key"),
                        scope_json=scope_json,
                        exceptions_json=exc_json,
                        source_trust=1.0,
                        rule_confidence=1.0,
                        scope_confidence=1.0,
                        evidence_count=0,
                        version=1,
                        current_version_id=new_ver_id,
                        valid_from=utc_now(),
                        created_at=utc_now(),
                        updated_at=utc_now(),
                    )
                    session.add(new_card)
                    session.add(
                        MemoryVersionModel(
                            id=new_ver_id,
                            owner_id=user_ctx.user_id,
                            memory_id=merged_id,
                            version=1,
                            title=body.merged_card.title,
                            rule=body.merged_card.rule,
                            avoid=body.merged_card.avoid or "",
                            trigger_text=body.merged_card.trigger_text or "",
                            scope_json=scope_json,
                            exceptions_json=exc_json,
                            created_by_action="merge",
                            created_at=utc_now(),
                        )
                    )
                    for src_id in (relation.from_memory_id, relation.to_memory_id):
                        card_repo.set_status(
                            src_id,
                            body.left_expected_current_version_id
                            if src_id == relation.from_memory_id
                            else body.right_expected_current_version_id,
                            "merged",
                        )
                        merged_into_id = new_prefixed_ulid("rel")
                        session.add(
                            MemoryRelationModel(
                                id=merged_into_id,
                                owner_id=user_ctx.user_id,
                                from_memory_id=src_id,
                                to_memory_id=merged_id,
                                relation_type="merged_into",
                                status="resolved",
                                resolved_at=utc_now(),
                                created_at=utc_now(),
                            )
                        )
                elif body.action == "pause_both":
                    for card_id, ver_id in [
                        (relation.from_memory_id, body.left_expected_current_version_id),
                        (relation.to_memory_id, body.right_expected_current_version_id),
                    ]:
                        card_repo.set_status(card_id, ver_id, "paused")
                conflict_repo.resolve(
                    relation_id,
                    action=body.action,
                    resolution_memory_id=resolution_memory_id,
                )
                for memory_id in (relation.from_memory_id, relation.to_memory_id):
                    TaskRepository(user_ctx, session).append_event(
                        stream_type="memory",
                        stream_id=memory_id,
                        seq=_next_metadata_event_seq(
                            session, user_ctx.user_id, "memory", memory_id
                        ),
                        event_type=EventType.MEMORY_CONFLICT_RESOLVED.value,
                        metadata={
                            "relation_id": relation_id,
                            "action": body.action,
                            "resolution_memory_id": resolution_memory_id,
                            "status": "resolved",
                        },
                    )
                session.flush()
                response_data = MemoryConflictResolveResponse(
                    request_id=request.state.request_id,
                    relation_id=relation_id,
                    action=body.action,
                ).model_dump(mode="json")
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=json.dumps(response_data),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            return _replay_idempotent_response(
                factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        return JSONResponse(content=response_data, status_code=200)

    @application.post(
        f"{API_PREFIX}/memories/merge",
        response_model=MemoryMergeResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def merge_memories(
        request: Request,
        body: MemoryMergeRequest,
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/memories/merge"
        route = f"POST:{path}"
        normalized = body.model_dump(mode="json")
        req_hash = compute_request_hash(method="POST", path=path, body=normalized)
        factory = request.app.state.db_session_factory
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=json.loads(existing.response_json),
                    )
                if body.left_memory_id == body.right_memory_id:
                    raise _memory_state_conflict("不能合并同一张 MemoryCard。")
                card_repo = MemoryCardG4Repository(user_ctx, session)
                left = card_repo.get_detail(body.left_memory_id)
                right = card_repo.get_detail(body.right_memory_id)
                if left is None or right is None:
                    raise _memory_not_found()
                if (
                    left.current_version_id != body.left_expected_current_version_id
                    or right.current_version_id != body.right_expected_current_version_id
                ):
                    raise _memory_version_conflict()
                if left.status not in {"active", "paused"} or right.status not in {
                    "active",
                    "paused",
                }:
                    raise _memory_state_conflict("只有 active 或 paused MemoryCard 可以合并。")
                existing_conflict = session.execute(
                    select(MemoryRelationModel).where(
                        and_(
                            MemoryRelationModel.owner_id == user_ctx.user_id,
                            MemoryRelationModel.relation_type == "conflicts_with",
                            MemoryRelationModel.status == "unresolved",
                            or_(
                                and_(
                                    MemoryRelationModel.from_memory_id == body.left_memory_id,
                                    MemoryRelationModel.to_memory_id == body.right_memory_id,
                                ),
                                and_(
                                    MemoryRelationModel.from_memory_id == body.right_memory_id,
                                    MemoryRelationModel.to_memory_id == body.left_memory_id,
                                ),
                            ),
                        )
                    )
                ).scalar_one_or_none()
                if existing_conflict is not None:
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.MEMORY_MERGE_CONFLICT,
                        message=(
                            "两端存在未解决冲突，请先通过 /memory-conflicts/{id}/resolve 解决。"
                        ),
                    )
                merged_id = new_prefixed_ulid("mem")
                MemoryMergeRepository(user_ctx, session).manual_merge(
                    merged_memory_id=merged_id,
                    left_memory_id=body.left_memory_id,
                    right_memory_id=body.right_memory_id,
                    merged_card_data=body.merged_card.model_dump(mode="json"),
                )
                response_data = MemoryMergeResponse(
                    request_id=request.state.request_id,
                    merged_memory_id=merged_id,
                    left_memory_id=body.left_memory_id,
                    right_memory_id=body.right_memory_id,
                ).model_dump(mode="json")
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=json.dumps(response_data),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
                session.flush()
        except IntegrityError:
            return _replay_idempotent_response(
                factory,
                user_ctx,
                route=route,
                idem_key=idem_key,
                req_hash=req_hash,
            )
        return JSONResponse(content=response_data, status_code=200)

    @application.post(
        f"{API_PREFIX}/memory-packs/export",
        response_model=MemoryPackDocument,
        responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    )
    async def export_memory_pack(
        request: Request,
        body: PackExportRequest,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            pack_repo = PackRepository(user_ctx, session)
            pack_id = new_prefixed_ulid("pack")
            name = body.name or f"memtrace-export-{pack_id[5:]}"
            try:
                pack = pack_repo.export_memories(
                    pack_id=pack_id,
                    name=name,
                    description=body.description or "",
                    memory_ids=body.memory_ids,
                )
            except ValueError as exc:
                raise _memory_not_found() from exc
            if not pack["cards"]:
                raise _memory_not_found()
            payload = PackRepository.canonical_bytes(pack)
            return Response(
                content=payload,
                media_type="application/json",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="memtrace-{pack_id}.mempack.json"'
                    )
                },
            )

    @application.post(
        f"{API_PREFIX}/memory-packs/import/preview",
        response_model=PackPreviewResponse,
        responses={
            401: {"model": ErrorEnvelope},
            413: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
        },
    )
    async def preview_memory_pack(
        request: Request,
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        idem_key = validate_idempotency_key(idempotency_key_raw)
        path = f"{API_PREFIX}/memory-packs/import/preview"
        route = f"POST:{path}"
        factory = request.app.state.db_session_factory
        body_bytes = await request.body()
        req_hash = compute_request_hash(method="POST", path=path, body=body_bytes.hex())
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing = idem_repo.get_record(route, idem_key)
                if existing is not None:
                    if existing.request_hash != req_hash:
                        raise _idempotency_conflict()
                    locator = json.loads(existing.response_json)
                    batch = ImportBatchRepository(user_ctx, session).get_batch(locator["batch_id"])
                    if batch is None:
                        raise ApiError(
                            status_code=500,
                            code=ErrorCode.INTERNAL_ERROR,
                            message="预览幂等记录已失去批次。",
                        )
                    return JSONResponse(
                        status_code=200,
                        content=_pack_preview_response(
                            request_id=locator["request_id"],
                            batch=batch,
                            secret=get_session_secret(resolved_settings),
                        ),
                    )
                pack_repo = PackRepository(user_ctx, session)
                analysis = analyze_pack(body_bytes, pack_repo.existing_cards_for_preview())
                counts = analysis.counts
                batch_id = new_prefixed_ulid("batch")
                expires_at = utc_now() + timedelta(
                    seconds=resolved_settings.import_preview_ttl_seconds
                )
                exp_ts = _as_utc_timestamp(expires_at)
                preview_token = PackRepository.encode_preview_token(
                    get_session_secret(resolved_settings),
                    user_ctx.user_id,
                    batch_id,
                    analysis.file_hash,
                    exp_ts,
                )
                preview_data = {
                    "pack_metadata": {
                        "name": analysis.pack["name"],
                        "description": analysis.pack["description"],
                        "format": analysis.pack["format"],
                        "format_version": analysis.pack["format_version"],
                        "producer": analysis.pack["producer"],
                        "source": analysis.pack["source"],
                    },
                    "items": analysis.items,
                    "frozen_legal_ids": [
                        item["external_id"]
                        for item in analysis.items
                        if item["classification"] == "legal_new"
                    ],
                }
                batch = ImportBatchRepository(user_ctx, session).create_batch(
                    batch_id=batch_id,
                    file_hash=analysis.file_hash,
                    pack_name=analysis.pack["name"],
                    format_version=analysis.pack["format_version"],
                    canonical_payload_json=analysis.canonical_json,
                    preview_json=json.dumps(
                        preview_data, ensure_ascii=False, separators=(",", ":")
                    ),
                    preview_token_hash=hashlib.sha256(preview_token.encode()).hexdigest(),
                    expires_at=expires_at,
                    legal_new_count=counts["legal_new"],
                    duplicate_count=counts["duplicate"],
                    conflict_count=counts["potential_conflict"],
                    suspicious_count=counts["suspicious"],
                )
                TaskRepository(user_ctx, session).append_event(
                    stream_type="import",
                    stream_id=batch_id,
                    seq=1,
                    event_type=EventType.MEMORY_PACK_PREVIEWED.value,
                    metadata={"batch_id": batch_id, **counts, "expires_at": exp_ts},
                )
                response_data = _pack_preview_response(
                    request_id=request.state.request_id,
                    batch=batch,
                    secret=get_session_secret(resolved_settings),
                    token=preview_token,
                )
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=json.dumps(
                        {"request_id": request.state.request_id, "batch_id": batch_id}
                    ),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            return _replay_pack_preview(
                factory,
                user_ctx,
                route,
                idem_key,
                req_hash,
                get_session_secret(resolved_settings),
            )
        except PackValidationError as exc:
            raise _error_response(
                request,
                status_code=exc.status_code,
                code=ErrorCode(exc.code),
                message=exc.message,
            ) from exc
        except ApiError:
            raise
        return JSONResponse(content=response_data, status_code=200)

    @application.post(
        f"{API_PREFIX}/memory-packs/import/commit",
        response_model=ImportCommitResponse,
        responses={
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    async def commit_memory_pack_import(
        request: Request,
        body: ImportCommitRequest,
        idempotency_key_raw: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_ctx: UserContext = Depends(get_current_user),
    ) -> Response:
        path = f"{API_PREFIX}/memory-packs/import/commit"
        route = f"POST:{path}"
        idem_key = validate_idempotency_key(idempotency_key_raw)
        req_hash = compute_request_hash(method="POST", path=path, body=body.model_dump(mode="json"))
        factory = request.app.state.db_session_factory
        try:
            with session_scope(factory) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                idem_repo = IdempotencyRepository(user_ctx, session)
                existing_idem = idem_repo.get_record(route, idem_key)
                if existing_idem is not None:
                    if existing_idem.request_hash != req_hash:
                        raise _idempotency_conflict()
                    return JSONResponse(
                        status_code=existing_idem.response_status,
                        content=json.loads(existing_idem.response_json),
                    )
                batch_repo = ImportBatchRepository(user_ctx, session)
                batch = batch_repo.get_batch(body.batch_id)
                if batch is None:
                    raise _error_response(
                        request,
                        status_code=404,
                        code=ErrorCode.IMPORT_BATCH_NOT_FOUND,
                        message="导入批次不存在或不属于当前用户。",
                    )
                if batch.status != "quarantined":
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.IMPORT_BATCH_STATE_CONFLICT,
                        message=f"批次状态为 {batch.status}，无法提交。",
                    )
                if _as_utc_timestamp(batch.expires_at) < _as_utc_timestamp(utc_now()):
                    batch.status = "expired"
                    batch.canonical_payload_json = None
                    batch.preview_json = None
                    batch.preview_token_hash = None
                    batch.updated_at = utc_now()
                    session.commit()
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.IMPORT_BATCH_EXPIRED,
                        message="预览批次已过期，请重新预览。",
                    )
                secret = get_session_secret(resolved_settings)
                exp_ts = _as_utc_timestamp(batch.expires_at)
                token_valid = PackRepository.verify_preview_token(
                    secret,
                    body.preview_token,
                    user_ctx.user_id,
                    body.batch_id,
                    batch.file_hash,
                    exp_ts,
                )
                token_hash_valid = secrets.compare_digest(
                    hashlib.sha256(body.preview_token.encode()).hexdigest(),
                    batch.preview_token_hash or "",
                )
                if not token_valid or not token_hash_valid:
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.IMPORT_PREVIEW_TOKEN_INVALID,
                        message="预览 token 文件哈希不匹配。",
                    )
                if not batch.canonical_payload_json or not batch.preview_json:
                    raise _error_response(
                        request,
                        status_code=409,
                        code=ErrorCode.IMPORT_BATCH_STATE_CONFLICT,
                        message="批次数据已清除，请重新预览。",
                    )
                pack_repo = PackRepository(user_ctx, session)
                analysis = analyze_pack(
                    batch.canonical_payload_json.encode("utf-8"),
                    pack_repo.existing_cards_for_preview(),
                )
                preview_data = json.loads(batch.preview_json)
                frozen_legal = set(preview_data["frozen_legal_ids"])
                current_legal = {
                    item["external_id"]
                    for item in analysis.items
                    if item["classification"] == "legal_new"
                }
                import_ids = frozen_legal & current_legal
                external_to_local: dict[str, str] = {}
                now = utc_now()
                for card_data in analysis.pack["cards"]:
                    external_id = card_data["external_id"]
                    if external_id not in import_ids:
                        continue
                    scope = card_data.get("scope", {})
                    scope_json = json.dumps(scope, separators=(",", ":"), ensure_ascii=False)
                    exc_json = json.dumps(
                        card_data.get("exceptions", []),
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    memory_id = new_prefixed_ulid("mem")
                    ver_id = new_prefixed_ulid("memver")
                    external_to_local[external_id] = memory_id
                    card = MemoryCardModel(
                        id=memory_id,
                        owner_id=user_ctx.user_id,
                        status="paused",
                        kind=card_data.get("kind", "preference"),
                        source_type="import",
                        save_preselected=False,
                        title=card_data.get("title", ""),
                        rule=card_data.get("rule", ""),
                        avoid=card_data.get("avoid", ""),
                        trigger_text=card_data.get("trigger_text", ""),
                        scope_level=scope.get("level", "global"),
                        domain=scope.get("domain", "other"),
                        task_type=scope.get("task_type"),
                        artifact_type=scope.get("artifact_type"),
                        audience=scope.get("audience"),
                        project_key=scope.get("project_key"),
                        scope_json=scope_json,
                        exceptions_json=exc_json,
                        source_trust=0.50,
                        rule_confidence=1.0,
                        scope_confidence=1.0,
                        evidence_count=0,
                        version=1,
                        current_version_id=ver_id,
                        valid_from=now,
                        import_batch_id=body.batch_id,
                        import_source_version=card_data.get("version", 1),
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(card)
                    session.add(
                        MemoryVersionModel(
                            id=ver_id,
                            owner_id=user_ctx.user_id,
                            memory_id=memory_id,
                            version=1,
                            title=card_data.get("title", ""),
                            rule=card_data.get("rule", ""),
                            avoid=card_data.get("avoid", ""),
                            trigger_text=card_data.get("trigger_text", ""),
                            scope_json=scope_json,
                            exceptions_json=exc_json,
                            created_by_action="import",
                            created_at=now,
                        )
                    )
                session.flush()
                for relation_data in analysis.pack["relations"]:
                    source = external_to_local.get(relation_data["from_external_id"])
                    target = external_to_local.get(relation_data["to_external_id"])
                    if source is None or target is None:
                        continue
                    session.add(
                        MemoryRelationModel(
                            id=new_prefixed_ulid("rel"),
                            owner_id=user_ctx.user_id,
                            from_memory_id=source,
                            to_memory_id=target,
                            relation_type=relation_data["relation_type"],
                            status="resolved",
                            resolved_at=now,
                            created_at=now,
                        )
                    )
                inserted = len(external_to_local)
                skipped = len(analysis.pack["cards"]) - inserted
                batch_repo.commit(body.batch_id, inserted, skipped)
                TaskRepository(user_ctx, session).append_event(
                    stream_type="import",
                    stream_id=body.batch_id,
                    seq=2,
                    event_type=EventType.MEMORY_PACK_COMMITTED.value,
                    metadata={
                        "batch_id": body.batch_id,
                        "inserted_count": inserted,
                        "skipped_count": skipped,
                    },
                )
                response_data = ImportCommitResponse(
                    request_id=request.state.request_id,
                    batch_id=body.batch_id,
                    inserted_count=inserted,
                    skipped_count=skipped,
                    warning_count=skipped,
                ).model_dump(mode="json")
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=200,
                    response_json=json.dumps(response_data),
                    expires_at=utc_now() + SESSION_DURATION * 2,
                )
        except IntegrityError:
            return _replay_idempotent_response(
                factory, user_ctx, route=route, idem_key=idem_key, req_hash=req_hash
            )
        except PackValidationError as exc:
            raise _error_response(
                request,
                status_code=exc.status_code,
                code=ErrorCode(exc.code),
                message=exc.message,
            ) from exc
        except ApiError:
            raise
        except Exception as exc:
            traceback_node = exc.__traceback__
            while traceback_node is not None and traceback_node.tb_next is not None:
                traceback_node = traceback_node.tb_next
            logger.error(
                "memory_pack.commit_failed type=%s line=%s",
                type(exc).__name__,
                traceback_node.tb_lineno if traceback_node is not None else 0,
            )
            raise _error_response(
                request,
                status_code=500,
                code=ErrorCode.INTERNAL_ERROR,
                message="提交导入时发生内部错误。",
            ) from None
        return JSONResponse(content=response_data, status_code=200)

    @application.get(
        f"{API_PREFIX}/memory-packs/import/{{batch_id}}",
        response_model=ImportBatchResponse,
        responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    )
    async def get_import_batch(
        request: Request,
        batch_id: str = Path(pattern=BATCH_ID_PATTERN),
        user_ctx: UserContext = Depends(get_current_user),
    ) -> ImportBatchResponse:
        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            batch_repo = ImportBatchRepository(user_ctx, session)
            batch = batch_repo.get_batch(batch_id)
            if batch is None:
                raise _error_response(
                    request,
                    status_code=404,
                    code=ErrorCode.IMPORT_BATCH_NOT_FOUND,
                    message="导入批次不存在或不属于当前用户。",
                )
            return ImportBatchResponse(
                request_id=request.state.request_id,
                batch_id=batch.id,
                status=batch.status,
                created_at=batch.created_at,
                expires_at=batch.expires_at,
                inserted_count=batch.inserted_count,
                skipped_count=batch.skipped_count,
                warning_count=batch.warning_count,
                error_message=batch.error_message,
            )

    web_dist = resolved_settings.memtrace_web_dist
    if web_dist is not None and web_dist.is_dir():
        assets_dir = web_dist / "assets"
        if assets_dir.is_dir():
            application.mount(
                "/assets",
                StaticFiles(directory=assets_dir, check_dir=True),
                name="web-assets",
            )

        @application.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            if full_path == "api" or full_path.startswith("api/"):
                raise StarletteHTTPException(status_code=404)

            root = web_dist.resolve()
            requested = (root / full_path).resolve()
            if requested.is_relative_to(root) and requested.is_file():
                return FileResponse(requested)
            index = root / "index.html"
            if index.is_file():
                return FileResponse(index)
            raise StarletteHTTPException(status_code=404)

    return application


def _memory_job_response(
    job: MemoryJobModel,
    *,
    request_id: str,
    candidate_ids: list[str],
) -> MemoryJobResponse:
    return MemoryJobResponse(
        request_id=request_id,
        memory_job_id=job.id,
        feedback_id=job.feedback_id,
        job_type="extract_feedback",
        status=job.status,
        stage=job.stage,
        attempt=job.attempt,
        candidate_ids=candidate_ids,
        disposition=job.disposition,
        error_code=job.last_error_code,
        retryable=job.retryable,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _card_projection(card: MemoryCardModel) -> MemoryCard:
    return MemoryCard(
        memory_id=card.id,
        kind=card.kind,
        title=card.title,
        rule=card.rule,
        avoid=card.avoid,
        trigger_text=card.trigger_text,
        scope=MemoryScope.model_validate_json(card.scope_json),
        exceptions=json.loads(card.exceptions_json),
        status=card.status,
        rejection_reason=card.rejection_reason,
        source_type=card.source_type,
        save_preselected=card.save_preselected,
        source_trust=card.source_trust,
        rule_confidence=card.rule_confidence,
        scope_confidence=card.scope_confidence,
        evidence_count=card.evidence_count,
        version=card.version,
        current_version_id=card.current_version_id,
        valid_from=card.valid_from,
        valid_to=card.valid_to,
        retrieved_count=card.retrieved_count,
        injected_count=card.injected_count,
        verified_applied_count=card.verified_applied_count,
        helpful_count=card.helpful_count,
        harmful_count=card.harmful_count,
        stale_count=card.stale_count,
        last_used_at=card.last_used_at,
        evidence_missing=card.evidence_missing,
        import_batch_id=card.import_batch_id,
        import_source_version=card.import_source_version,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _evidence_projection(evidence: MemoryEvidenceModel) -> MemoryEvidenceProjection:
    return MemoryEvidenceProjection(
        evidence_id=evidence.id,
        source_type=evidence.source_type,
        feedback_id=evidence.feedback_id,
        task_id=evidence.task_id,
        run_id=evidence.run_id,
        evidence_quote=evidence.evidence_quote[:2_000],
        diff_summary=evidence.diff_summary_json,
        normalized_edit_cost=evidence.normalized_edit_cost,
        created_at=evidence.created_at,
    )


def _version_projection(version: MemoryVersionModel) -> MemoryVersionProjection:
    return MemoryVersionProjection(
        memory_version_id=version.id,
        version=version.version,
        title=version.title,
        rule=version.rule,
        avoid=version.avoid,
        trigger_text=version.trigger_text,
        scope=MemoryScope.model_validate_json(version.scope_json),
        exceptions=json.loads(version.exceptions_json),
        created_by_action=version.created_by_action,
        created_at=version.created_at,
    )


def _relation_projection(relation: MemoryRelationModel) -> MemoryRelationProjection:
    return MemoryRelationProjection(
        relation_id=relation.id,
        from_memory_id=relation.from_memory_id,
        to_memory_id=relation.to_memory_id,
        relation_type=relation.relation_type,
        status=relation.status,
        resolution_action=relation.resolution_action,
        resolution_memory_id=relation.resolution_memory_id,
        created_at=relation.created_at,
        resolved_at=relation.resolved_at,
    )


def _resolved_card_values(card: MemoryCardModel, body: ResolveRequest) -> dict[str, object]:
    scope = MemoryScope.model_validate_json(card.scope_json)
    title = card.title
    rule = card.rule
    avoid = card.avoid
    trigger_text = card.trigger_text
    exceptions = json.loads(card.exceptions_json)
    if body.action is ResolveAction.EDIT_ACCEPT:
        assert body.patch is not None
        if body.patch.title is not None:
            title = body.patch.title
        if body.patch.rule is not None:
            rule = body.patch.rule
        if body.patch.avoid is not None:
            avoid = body.patch.avoid
        if body.patch.trigger_text is not None:
            trigger_text = body.patch.trigger_text
        if body.patch.scope is not None:
            scope = body.patch.scope
        if body.patch.exceptions is not None:
            exceptions = [item.value for item in body.patch.exceptions]
    scope_json = scope.model_dump(mode="json")
    return {
        "title": title,
        "rule": rule,
        "avoid": avoid,
        "trigger_text": trigger_text,
        "scope_level": scope_json["level"],
        "domain": scope_json["domain"],
        "task_type": scope_json.get("task_type"),
        "artifact_type": scope_json.get("artifact_type"),
        "audience": scope_json.get("audience"),
        "project_key": scope_json.get("project_key"),
        "scope_json": json.dumps(scope_json, separators=(",", ":"), ensure_ascii=False),
        "exceptions_json": json.dumps(
            exceptions,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }


def _enforce_resolve_admission_guard(
    *,
    card: MemoryCardModel,
    values: dict[str, object],
    evidence: MemoryEvidenceModel,
    feedback: FeedbackEventModel,
    fingerprint: TaskFingerprint,
) -> None:
    scope_json = values["scope_json"]
    exceptions_json = values["exceptions_json"]
    assert isinstance(scope_json, str)
    assert isinstance(exceptions_json, str)
    evidence_source = (
        "explicit_text"
        if evidence.source_type in {"explicit_feedback", "explicit_correction"}
        else "edit_diff"
    )
    candidate = {
        "category": "preference" if card.kind == "preference" else "rule",
        "kind": card.kind,
        "title": values["title"],
        "rule": values["rule"],
        "avoid": values["avoid"],
        "trigger_text": values["trigger_text"],
        "scope": json.loads(scope_json),
        "exceptions": json.loads(exceptions_json),
        "evidence_source": evidence_source,
        "evidence_quote": evidence.evidence_quote,
    }
    decision = run_all_gates(
        candidate=candidate,
        durability="explicit_durable",
        feedback_text=feedback.explicit_text,
        edited_output=feedback.edited_output,
        fingerprint=fingerprint,
    )
    if not decision.all_passed:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message=(
                "编辑后的候选未通过 Admission Guard："
                f"{decision.blocking_gate}/{decision.final_decision.reason}。"
            ),
        )


async def _broadcast_persisted_event(
    store: TaskStore,
    user_ctx: UserContext,
    *,
    task_id: str,
    event_type: EventType,
    event_seq: int,
    data: dict[str, object],
) -> None:
    try:
        record = await store.get(task_id)
        if record.user_ctx is not None and record.user_ctx.user_id != user_ctx.user_id:
            return
        await store.emit_preallocated_persistent(
            record,
            event_type=event_type,
            event_seq=event_seq,
            data=data,
        )
    except (TaskMissingError, ReplayCapacityError):
        return
    except Exception as exc:
        logger.warning("memory.broadcast_failed type=%s", type(exc).__name__)


def _memory_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code=ErrorCode.MEMORY_NOT_FOUND,
        message="指定的记忆对象不存在或无权访问。",
    )


def _allocate_memory_event_seq(session: Session, owner_id: str, stream_id: str) -> int:
    return _next_metadata_event_seq(session, owner_id, "memory", stream_id)


def _next_metadata_event_seq(
    session: Session,
    owner_id: str,
    stream_type: str,
    stream_id: str,
) -> int:
    """Allocate a stream-local sequence while the caller holds BEGIN IMMEDIATE."""
    value = session.execute(
        select(func.coalesce(func.max(EventLogModel.seq), 0)).where(
            and_(
                EventLogModel.owner_id == owner_id,
                EventLogModel.stream_type == stream_type,
                EventLogModel.stream_id == stream_id,
            )
        )
    ).scalar_one()
    return int(value) + 1


def _memory_state_conflict(message: str) -> ApiError:
    return ApiError(
        status_code=409,
        code=ErrorCode.MEMORY_STATE_CONFLICT,
        message=message,
    )


def _memory_version_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code=ErrorCode.MEMORY_VERSION_CONFLICT,
        message="MemoryCard 已被更新，请刷新后基于最新版本重试。",
    )


def _enforce_active_invariants(card: MemoryCardModel) -> None:
    if (
        card.current_version_id is None
        or card.version < 1
        or card.rule_confidence is None
        or card.scope_confidence is None
    ):
        raise _memory_state_conflict("MemoryCard 不满足 active 状态不变量。")


def _scope_overlap_v1(left: MemoryScope, right: MemoryScope) -> bool:
    left_data = left.model_dump(mode="json")
    right_data = right.model_dump(mode="json")
    for field in (
        "domain",
        "task_type",
        "artifact_type",
        "audience",
        "project_key",
        "language",
        "framework",
    ):
        left_value = left_data.get(field)
        right_value = right_data.get(field)
        if (
            left_value not in {None, "any"}
            and right_value not in {None, "any"}
            and left_value != right_value
        ):
            return False
    return True


def _active_edit_values(
    card: MemoryCardModel,
    body: ActiveMemoryEditRequest,
) -> dict[str, object]:
    scope = MemoryScope.model_validate_json(card.scope_json)
    title = card.title
    rule = card.rule
    avoid = card.avoid
    trigger_text = card.trigger_text
    exceptions = json.loads(card.exceptions_json)
    if body.patch.title is not None:
        title = body.patch.title
    if body.patch.rule is not None:
        rule = body.patch.rule
    if body.patch.avoid is not None:
        avoid = body.patch.avoid
    if body.patch.trigger_text is not None:
        trigger_text = body.patch.trigger_text
    if body.patch.scope is not None:
        scope = body.patch.scope
    if body.patch.exceptions is not None:
        exceptions = [item.value for item in body.patch.exceptions]
    scope_data = scope.model_dump(mode="json")
    return {
        "title": title,
        "rule": rule,
        "avoid": avoid,
        "trigger_text": trigger_text,
        "scope_level": scope_data["level"],
        "domain": scope_data["domain"],
        "task_type": scope_data.get("task_type"),
        "artifact_type": scope_data.get("artifact_type"),
        "audience": scope_data.get("audience"),
        "project_key": scope_data.get("project_key"),
        "scope_json": json.dumps(scope_data, separators=(",", ":"), ensure_ascii=False),
        "exceptions_json": json.dumps(
            exceptions,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }


def _idempotency_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code=ErrorCode.IDEMPOTENCY_CONFLICT,
        message="Idempotency-Key 已用于不同的请求载荷。",
    )


def _memory_cursor_filter_hash(filters: MemoryListFilter) -> str:
    payload = filters.model_dump(mode="json", exclude={"cursor"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _encode_memory_cursor(filters: MemoryListFilter, card: MemoryCardModel) -> str:
    sort_value: datetime | str | None
    if filters.sort == "title_asc":
        sort_value = card.title
    elif filters.sort == "created_desc":
        sort_value = card.created_at
    elif filters.sort == "last_used_desc":
        sort_value = card.last_used_at
    else:
        sort_value = card.updated_at
    if isinstance(sort_value, datetime):
        if sort_value.tzinfo is None:
            sort_value = sort_value.replace(tzinfo=UTC)
        encoded_value: str | None = sort_value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    else:
        encoded_value = sort_value
    payload = {
        "v": 1,
        "f": _memory_cursor_filter_hash(filters),
        "s": filters.sort,
        "k": encoded_value,
        "i": card.id,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_memory_cursor(
    filters: MemoryListFilter,
) -> tuple[datetime | str | None, str | None]:
    if filters.cursor is None:
        return None, None
    try:
        padding = "=" * (-len(filters.cursor) % 4)
        raw = base64.urlsafe_b64decode(filters.cursor + padding)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"v", "f", "s", "k", "i"}:
            raise ValueError("shape")
        if payload["v"] != 1 or payload["s"] != filters.sort:
            raise ValueError("version or sort")
        if payload["f"] != _memory_cursor_filter_hash(filters):
            raise ValueError("filter")
        memory_id = payload["i"]
        if not isinstance(memory_id, str) or re.fullmatch(MEMORY_ID_PATTERN, memory_id) is None:
            raise ValueError("memory id")
        value = payload["k"]
        if filters.sort == "title_asc":
            if not isinstance(value, str):
                raise ValueError("title")
            return value, memory_id
        if filters.sort == "last_used_desc" and value is None:
            return None, memory_id
        if not isinstance(value, str):
            raise ValueError("datetime")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone")
        return parsed.astimezone(UTC), memory_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raise ApiError(
            status_code=422,
            code=ErrorCode.INVALID_CURSOR,
            message="Memory Center cursor 无效或与当前筛选条件不匹配。",
        ) from exc


def _as_utc_timestamp(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.astimezone(UTC).timestamp())


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    retryable: bool = False,
    details: dict[str, object] | None = None,
) -> ApiError:
    """Create a typed API error; the installed handler renders the JSON envelope."""
    return ApiError(
        status_code=status_code,
        code=code,
        message=message,
        retryable=retryable,
        details=details,
    )


def _pack_preview_response(
    *,
    request_id: str,
    batch: ImportBatchModel,
    secret: str,
    token: str | None = None,
) -> dict[str, object]:
    if batch.status != "quarantined" or not batch.preview_json:
        raise ApiError(
            status_code=409,
            code=ErrorCode.IMPORT_BATCH_STATE_CONFLICT,
            message="预览批次已不可重放。",
        )
    preview = json.loads(batch.preview_json)
    items = preview["items"]
    counts = {
        name: sum(item["classification"] == name for item in items)
        for name in ("legal_new", "duplicate", "potential_conflict", "suspicious")
    }
    if token is None:
        token = PackRepository.encode_preview_token(
            secret,
            batch.owner_id,
            batch.id,
            batch.file_hash,
            _as_utc_timestamp(batch.expires_at),
        )
        if not secrets.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), batch.preview_token_hash or ""
        ):
            raise ApiError(
                status_code=409,
                code=ErrorCode.IMPORT_PREVIEW_TOKEN_INVALID,
                message="会话密钥已变化，请重新预览 Memory Pack。",
            )
    return PackPreviewResponse(
        request_id=request_id,
        batch_id=batch.id,
        pack_metadata=preview["pack_metadata"],
        legal_new_count=counts["legal_new"],
        duplicate_count=counts["duplicate"],
        potential_conflict_count=counts["potential_conflict"],
        suspicious_count=counts["suspicious"],
        items=[PackPreviewItem.model_validate(item) for item in items],
        preview_token=token,
    ).model_dump(mode="json")


def _replay_pack_preview(
    session_factory: sessionmaker[Session],
    user_ctx: UserContext,
    route: str,
    idem_key: str,
    req_hash: str,
    secret: str,
) -> JSONResponse:
    with session_scope(session_factory) as session:
        record = IdempotencyRepository(user_ctx, session).get_record(route, idem_key)
        if record is None:
            raise ApiError(
                status_code=500,
                code=ErrorCode.INTERNAL_ERROR,
                message="预览幂等竞态后未找到记录。",
            )
        if record.request_hash != req_hash:
            raise _idempotency_conflict()
        locator = json.loads(record.response_json)
        batch = ImportBatchRepository(user_ctx, session).get_batch(locator["batch_id"])
        if batch is None:
            raise ApiError(
                status_code=500,
                code=ErrorCode.INTERNAL_ERROR,
                message="预览批次不可恢复。",
            )
        return JSONResponse(
            status_code=record.response_status,
            content=_pack_preview_response(
                request_id=locator["request_id"], batch=batch, secret=secret
            ),
        )


def _replay_idempotent_response(
    session_factory: sessionmaker[Session],
    user_ctx: UserContext,
    *,
    route: str,
    idem_key: str,
    req_hash: str,
) -> JSONResponse:
    """Read the already-committed idempotency record and return replay or 409.

    Called when a unique-constraint race is detected on the idempotency table.
    The winning transaction's record is now committed, so a fresh read returns
    either the original response (same request hash) or a conflict.
    """
    with session_scope(session_factory) as session:
        idem_repo = IdempotencyRepository(user_ctx, session)
        existing = idem_repo.get_record(route, idem_key)
        if existing is None:
            raise ApiError(
                status_code=500,
                code=ErrorCode.INTERNAL_ERROR,
                message="幂等记录竞态后未找到已提交记录。",
                retryable=True,
            )
        if existing.request_hash != req_hash:
            raise ApiError(
                status_code=409,
                code=ErrorCode.IDEMPOTENCY_CONFLICT,
                message="Idempotency-Key 冲突：同一 Key 已用于不同的请求载荷。",
            )
        saved_json = json.loads(existing.response_json)
        return JSONResponse(status_code=existing.response_status, content=saved_json)


async def _db_subscription(
    *,
    session_factory: sessionmaker[Session],
    user_ctx: UserContext,
    task_id: str,
    after_event_seq: int,
) -> Subscription:
    from memtrace_api.store import ReplayEntry

    with session_scope(session_factory) as session:
        task_repo = TaskRepository(user_ctx, session)
        db_events = task_repo.list_events_after(
            stream_type="task",
            stream_id=task_id,
            after_event_seq=after_event_seq,
        )
        # Reconstruct the run_id that produced this task stream's events. The
        # event_log stores metadata only (no run_id), so resolve it from the
        # task's latest run for a valid EventEnvelope correlation.
        latest_run = task_repo.get_latest_run(task_id)
        run_id = latest_run.id if latest_run is not None else None
        replay_entries: list[ReplayEntry] = []
        for i, ev in enumerate(db_events, start=1):
            env = make_event(
                event_type=EventType(ev.event_type),
                event_seq=ev.seq,
                task_id=task_id,
                run_id=run_id,
                data=json.loads(ev.metadata_json),
            )
            replay_entries.append(ReplayEntry(ordinal=i, event=env))

    return Subscription(
        store=None,
        record=None,
        replay=replay_entries,
        subscriber=None,
        closed_at_capture=True,
    )


def _build_available_provider(settings: Settings) -> StreamingProvider | None:
    if settings.mock_mode:
        return MockProvider(chunk_delay_seconds=settings.mock_chunk_delay_ms / 1000)
    if settings.has_llm_api_key:
        return DeepSeekProvider(settings)
    return None


def _task_not_found(task_id: str) -> ApiError:
    return ApiError(
        status_code=404,
        code=ErrorCode.TASK_NOT_FOUND,
        message="任务不存在或已因进程重启而失效。",
        retryable=False,
        details=ErrorDetails(task_id=task_id),
    )


def _valid_last_event_id(value: str | None) -> int:
    if value is None or len(value) > 20 or not value.isascii() or not value.isdecimal():
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


async def _subscription_body(
    subscription: Subscription,
    heartbeat_seconds: float,
) -> AsyncIterator[bytes]:
    try:
        for index, entry in enumerate(subscription.replay):
            yield serialize_sse(entry.event)
            if (
                entry.event.event_type is EventType.STREAM_DONE
                and index == len(subscription.replay) - 1
            ):
                return
        if subscription.closed_at_capture or subscription.subscriber is None:
            return

        subscriber = subscription.subscriber
        while True:
            if subscriber.dropped:
                return
            try:
                entry = await asyncio.wait_for(
                    subscriber.queue.get(),
                    timeout=heartbeat_seconds,
                )
            except TimeoutError:
                if subscriber.dropped:
                    return
                yield b": heartbeat\n\n"
                continue
            yield serialize_sse(entry.event)
            if entry.event.event_type is EventType.STREAM_DONE:
                return
    finally:
        await subscription.close()


app = create_app()
