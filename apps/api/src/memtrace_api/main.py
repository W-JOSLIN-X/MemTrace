"""FastAPI application factory for the MemTrace service."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Request

from memtrace_api.config import Settings, get_settings
from memtrace_api.errors import ApiError, ErrorCode, ErrorEnvelope, install_exception_handlers
from memtrace_api.logging_config import configure_logging
from memtrace_api.middleware import RequestIdMiddleware
from memtrace_api.readiness import ensure_directory_writable
from memtrace_api.schemas import HealthResponse, ReadinessChecks, ReadyResponse

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
    )
    application.state.settings = resolved_settings
    application.add_middleware(RequestIdMiddleware)
    install_exception_handlers(application)

    @application.get(f"{API_PREFIX}/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        current: Settings = request.app.state.settings
        return HealthResponse(
            request_id=request.state.request_id,
            version=current.app_version,
            environment=current.app_env,
            at=datetime.now(UTC),
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
            provider_mode=current.provider_mode,
            checks=ReadinessChecks(
                provider_credentials="not_required" if current.mock_mode else "pass"
            ),
            at=datetime.now(UTC),
        )

    return application


app = create_app()
