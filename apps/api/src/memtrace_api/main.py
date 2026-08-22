"""FastAPI application factory and G1 REST/SSE routes."""

from __future__ import annotations

import asyncio
import inspect
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, Header, Path, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from memtrace_api.config import Settings, get_settings
from memtrace_api.database import create_db_engine, create_session_factory, session_scope
from memtrace_api.db_models import DemoSessionModel, MessageModel
from memtrace_api.errors import (
    ApiError,
    ErrorCode,
    ErrorDetails,
    ErrorEnvelope,
    install_exception_handlers,
)
from memtrace_api.events import EventType, make_event, serialize_sse
from memtrace_api.idempotency import compute_request_hash, validate_idempotency_key
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.logging_config import configure_logging
from memtrace_api.logic import analyze_task
from memtrace_api.middleware import RequestIdMiddleware
from memtrace_api.orchestrator import AgentOrchestrator
from memtrace_api.providers import DeepSeekProvider, MockProvider, StreamingProvider
from memtrace_api.readiness import ensure_directory_writable
from memtrace_api.repositories import (
    FeedbackRepository,
    IdempotencyRepository,
    SessionRepository,
    TaskRepository,
    UserContext,
    UserRepository,
)
from memtrace_api.schemas import (
    DemoAlias,
    DemoSessionCreateRequest,
    DemoSessionResponse,
    FeedbackCreateAccepted,
    FeedbackCreateRequest,
    HealthResponse,
    MemoryJobResponse,
    MessageRole,
    ProviderMode,
    ReadinessChecks,
    ReadyResponse,
    RunStatus,
    TaskCreateAccepted,
    TaskCreateRequest,
    TaskSnapshot,
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
    Subscription,
    SubscriptionCapacityError,
    TaskCapacityError,
    TaskMissingError,
    TaskRecord,
    TaskStore,
)

API_PREFIX = "/api/v1"
TASK_ID_PATTERN = r"^task_[0-9A-HJKMNP-TV-Z]{26}$"
JOB_ID_PATTERN = r"^job_[0-9A-HJKMNP-TV-Z]{26}$"


def create_app(
    settings: Settings | None = None,
    *,
    provider: StreamingProvider | None = None,
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Startup logic: ensure demo users and cleanup interrupted runs. Doing
        # this here (not at import time) keeps ``create_app`` side-effect free
        # and lets tests build an app without touching the default database.
        with session_scope(factory) as session:
            UserRepository(session).ensure_demo_users()
            raw_user_ctx = UserContext(user_id="bootstrap", demo_alias="bootstrap")
            TaskRepository(raw_user_ctx, session).cleanup_interrupted_runs()

        yield
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
            ensure_directory_writable(current.memtrace_data_dir)
        except OSError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="运行数据目录不可写。",
                retryable=True,
                details={"check": "data_directory"},
            ) from exc

        # Check DB readiness
        try:
            with session_scope(request.app.state.db_session_factory) as session:
                UserRepository(session).ensure_demo_users()
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="数据库连接不可用。",
                retryable=True,
            ) from exc

        return ReadyResponse(
            request_id=request.state.request_id,
            provider_mode=ProviderMode(current.provider_mode),
            checks=ReadinessChecks(
                provider_credentials="not_required" if current.mock_mode else "pass"
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
    ) -> DemoSessionResponse:
        settings: Settings = request.app.state.settings
        secret = get_session_secret(settings)
        token = secrets.token_urlsafe(32)
        token_h = hash_token(token)
        cookie_val = sign_cookie_value(token, secret)
        expires_at = utc_now() + SESSION_DURATION

        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            user_repo = UserRepository(session)
            user = user_repo.get_by_alias(body.demo_alias.value)
            if user is None:
                # bootstrap users
                users = user_repo.ensure_demo_users()
                user = users[body.demo_alias.value]
            session_repo = SessionRepository(session)
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
        # Get active session
        session_factory = request.app.state.db_session_factory
        expires_at = utc_now() + SESSION_DURATION
        with session_scope(session_factory) as session:
            row = (
                session.execute(
                    select(DemoSessionModel)
                    .where(
                        and_(
                            DemoSessionModel.owner_id == user_ctx.user_id,
                            DemoSessionModel.revoked_at.is_(None),
                        )
                    )
                    .order_by(DemoSessionModel.created_at.desc())
                )
                .scalars()
                .first()
            )
            if row is not None:
                expires_at = row.expires_at

        return DemoSessionResponse(
            request_id=request.state.request_id,
            demo_alias=DemoAlias(user_ctx.demo_alias),
            expires_at=expires_at,
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

        should_start_orchestrator = False
        try:
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
                    # Same payload replay
                    saved_json = json.loads(existing.response_json)
                    return JSONResponse(status_code=existing.response_status, content=saved_json)

                # Insert task in DB
                analysis = analyze_task(body)
                task_repo = TaskRepository(user_ctx, session)
                task_repo.create_task(
                    task_id=task_id,
                    run_id=run_id,
                    request=body,
                    detected_domain=analysis.fingerprint.domain,
                    provider_mode=current_orchestrator.provider.mode,
                    model=current_orchestrator.provider.model,
                )
                # Save idempotency record
                idem_repo.save_record(
                    route=route,
                    key=idem_key,
                    request_hash=req_hash,
                    response_status=202,
                    response_json=accepted_payload.model_dump_json(),
                    expires_at=utc_now() + SESSION_DURATION * 2,  # 24 hours
                )
                should_start_orchestrator = True
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

        # Now register in live TaskStore and start orchestrator
        if should_start_orchestrator:
            try:
                record = await resolved_store.create(
                    request=body,
                    analysis=analysis,
                    request_id=request.state.request_id,
                    provider_mode=current_orchestrator.provider.mode,
                    task_id=task_id,
                    run_id=run_id,
                    user_ctx=user_ctx,
                )
            except TaskCapacityError as exc:
                raise ApiError(
                    status_code=503,
                    code=ErrorCode.INTERNAL_ERROR,
                    message="当前运行中的任务已达到容量上限。",
                    retryable=True,
                ) from exc
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
        try:
            live_record = await resolved_store.get(task_id)
            if (
                live_record.user_ctx is not None
                and live_record.user_ctx.user_id != user_ctx.user_id
            ):
                raise _task_not_found(task_id)
            if not live_record.closed:
                return await resolved_store.snapshot(task_id, request_id=request.state.request_id)
        except TaskMissingError:
            pass

        # Fallback to database snapshot
        session_factory = request.app.state.db_session_factory
        with session_scope(session_factory) as session:
            task_repo = TaskRepository(user_ctx, session)
            snap = task_repo.get_snapshot(task_id, request_id=request.state.request_id)
            if snap is None:
                raise _task_not_found(task_id)
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
                subscription._record.user_ctx is not None
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
            fb_repo = FeedbackRepository(user_ctx, session)
            job = fb_repo.get_memory_job(job_id)
            if job is None:
                raise ApiError(
                    status_code=404,
                    code=ErrorCode.TASK_NOT_FOUND,
                    message="指定的 Memory Job 不存在或无权访问。",
                )
            return MemoryJobResponse(
                request_id=request.state.request_id,
                memory_job_id=job.id,
                job_type="extract_feedback",
                status=job.status,
                stage=job.stage,
                attempt=job.attempt,
                error=job.last_error_code,
                created_at=job.created_at,
                updated_at=job.updated_at,
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

    dummy_store = TaskStore(max_tasks=1, max_subscribers_per_task=1, subscriber_queue_size=1)
    dummy_task = TaskRecord(
        request=None,  # type: ignore[arg-type]
        snapshot=None,  # type: ignore[arg-type]
        closed=True,
    )
    return Subscription(
        store=dummy_store,
        record=dummy_task,
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
        for entry in subscription.replay:
            yield serialize_sse(entry.event)
            if entry.event.event_type is EventType.STREAM_DONE:
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
