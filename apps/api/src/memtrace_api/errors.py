"""Contract-aligned API errors and exception handlers."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from memtrace_api.ids import new_prefixed_ulid

logger = logging.getLogger(__name__)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    PROVIDER_CONFIG_MISSING = "PROVIDER_CONFIG_MISSING"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_INPUT_INVALID = "TOOL_INPUT_INVALID"
    STREAM_INTERRUPTED = "STREAM_INTERRUPTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # Day 2 G1 additions. These are REST-level codes; async run failures still
    # use AsyncErrorCode above. SESSION_REQUIRED is the single 401 for any
    # missing, expired, revoked, or tampered demo-session cookie so that the
    # response never leaks whether a session ever existed.
    SESSION_REQUIRED = "SESSION_REQUIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    FEEDBACK_NO_CHANGES = "FEEDBACK_NO_CHANGES"
    TASK_NOT_READY_FOR_FEEDBACK = "TASK_NOT_READY_FOR_FEEDBACK"


class ValidationFieldError(ContractModel):
    loc: list[str | int]
    message: str
    type: str


class ErrorDetails(ContractModel):
    field_errors: Annotated[list[ValidationFieldError], Field(max_length=50)] | None = None
    task_id: str | None = None
    run_id: str | None = None
    provider_status: int | None = Field(default=None, ge=400, le=599)
    check: Literal["provider_configuration", "data_directory"] | None = None
    http_status: int | None = Field(default=None, ge=400, le=599)


class ErrorDetail(ContractModel):
    code: ErrorCode
    message: str
    request_id: str
    retryable: bool = False
    details: ErrorDetails = Field(default_factory=ErrorDetails)


class ErrorEnvelope(ContractModel):
    error: ErrorDetail


class ApiError(Exception):
    """Expected operational error rendered with the public error envelope."""

    def __init__(
        self,
        *,
        status_code: int,
        code: ErrorCode,
        message: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", new_prefixed_ulid("req"))


def build_error_content(
    *,
    request_id: str,
    code: ErrorCode,
    message: str,
    retryable: bool = False,
    details: ErrorDetails | dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=request_id,
            retryable=retryable,
            details=details or ErrorDetails(),
        )
    )
    return payload.model_dump(mode="json", exclude_none=True)


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    retryable: bool = False,
    details: ErrorDetails | dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_error_content(
            request_id=_request_id(request),
            code=code,
            message=message,
            retryable=retryable,
            details=details,
        ),
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            ValidationFieldError(
                loc=[
                    part if isinstance(part, (str, int)) else str(part)
                    for part in error.get("loc", ())
                ],
                message=error.get("msg", "输入无效。"),
                type=error.get("type", "validation_error"),
            )
            for error in exc.errors()[:50]
        ]
        return _error_response(
            request,
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="请求参数校验失败。",
            details=ErrorDetails(field_errors=safe_errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=ErrorCode.VALIDATION_ERROR,
            message="请求的资源或方法不存在。",
            details=ErrorDetails(http_status=exc.status_code),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("request.unexpected_error type=%s", type(exc).__name__)
        return _error_response(
            request,
            status_code=500,
            code=ErrorCode.INTERNAL_ERROR,
            message="服务处理请求时发生内部错误。",
            retryable=False,
        )
