"""FastAPI application factory and G0 REST/SSE routes."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Path, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from memtrace_api.config import Settings, get_settings
from memtrace_api.errors import (
    ApiError,
    ErrorCode,
    ErrorDetails,
    ErrorEnvelope,
    install_exception_handlers,
)
from memtrace_api.events import EventType, serialize_sse
from memtrace_api.logging_config import configure_logging
from memtrace_api.middleware import RequestIdMiddleware
from memtrace_api.orchestrator import AgentOrchestrator
from memtrace_api.providers import DeepSeekProvider, MockProvider, StreamingProvider
from memtrace_api.readiness import ensure_directory_writable
from memtrace_api.schemas import (
    HealthResponse,
    ProviderMode,
    ReadinessChecks,
    ReadyResponse,
    TaskCreateAccepted,
    TaskCreateRequest,
    TaskSnapshot,
    utc_now,
)
from memtrace_api.store import (
    Subscription,
    SubscriptionCapacityError,
    TaskCapacityError,
    TaskMissingError,
    TaskStore,
)

API_PREFIX = "/api/v1"
TASK_ID_PATTERN = r"^task_[0-9A-HJKMNP-TV-Z]{26}$"


def create_app(
    settings: Settings | None = None,
    *,
    provider: StreamingProvider | None = None,
    store: TaskStore | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    resolved_store = store or TaskStore(
        max_tasks=resolved_settings.max_tasks,
        max_subscribers_per_task=resolved_settings.max_subscribers_per_task,
        subscriber_queue_size=resolved_settings.subscriber_queue_size,
    )
    resolved_provider = provider or _build_available_provider(resolved_settings)
    orchestrator = (
        AgentOrchestrator(store=resolved_store, provider=resolved_provider)
        if resolved_provider is not None
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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
        return ReadyResponse(
            request_id=request.state.request_id,
            provider_mode=ProviderMode(current.provider_mode),
            checks=ReadinessChecks(
                provider_credentials="not_required" if current.mock_mode else "pass"
            ),
            at=utc_now(),
        )

    @application.post(
        f"{API_PREFIX}/tasks",
        response_model=TaskCreateAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            422: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope},
        },
    )
    async def create_task(request: Request, body: TaskCreateRequest) -> TaskCreateAccepted:
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
        try:
            record = await resolved_store.create(
                request=body,
                request_id=request.state.request_id,
                provider_mode=current_orchestrator.provider.mode,
            )
        except TaskCapacityError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.INTERNAL_ERROR,
                message="当前运行中的任务已达到容量上限。",
                retryable=True,
            ) from exc
        current_orchestrator.start(record)
        return TaskCreateAccepted(
            request_id=request.state.request_id,
            task_id=record.snapshot.task_id,
            run_id=record.snapshot.run_id,
            events_url=f"{API_PREFIX}/tasks/{record.snapshot.task_id}/events",
            provider_mode=current_orchestrator.provider.mode,
            effective_memory_mode=body.effective_memory_mode,
        )

    @application.get(
        f"{API_PREFIX}/tasks/{{task_id}}",
        response_model=TaskSnapshot,
        responses={
            404: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
        },
    )
    async def get_task(
        request: Request,
        task_id: str = Path(pattern=TASK_ID_PATTERN),
    ) -> TaskSnapshot:
        try:
            return await resolved_store.snapshot(task_id, request_id=request.state.request_id)
        except TaskMissingError as exc:
            raise _task_not_found(task_id) from exc

    @application.get(
        f"{API_PREFIX}/tasks/{{task_id}}/events",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "G0 task event stream",
                "content": {
                    "text/event-stream": {
                        "schema": {"type": "string"},
                    }
                },
            },
            404: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope},
        },
    )
    async def task_events(
        task_id: str = Path(pattern=TASK_ID_PATTERN),
        after_event_seq: int | None = Query(default=None, ge=0),
        after_offset: int = Query(default=0, ge=0, le=262_144),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        cursor = (
            after_event_seq if after_event_seq is not None else _valid_last_event_id(last_event_id)
        )
        try:
            subscription = await resolved_store.open_subscription(
                task_id,
                after_event_seq=cursor,
                after_offset=after_offset,
            )
        except TaskMissingError as exc:
            raise _task_not_found(task_id) from exc
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
