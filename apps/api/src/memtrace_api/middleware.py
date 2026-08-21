"""ASGI middleware that remains safe when streaming responses are added."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from memtrace_api.errors import ErrorCode, build_error_content
from memtrace_api.ids import new_prefixed_ulid

logger = logging.getLogger(__name__)

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RequestIdMiddleware:
    """Attach a server-generated request ID without buffering response bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = new_prefixed_ulid("req")
        state: MutableMapping[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        started_at = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception(
                "request.failed method=%s path=%s request_id=%s",
                scope.get("method", ""),
                scope.get("path", ""),
                request_id,
            )
            if response_started:
                raise
            response = JSONResponse(
                status_code=500,
                content=build_error_content(
                    request_id=request_id,
                    code=ErrorCode.INTERNAL_ERROR,
                    message="服务发生未预期错误。",
                ),
            )
            await response(scope, receive, send_with_request_id)
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "request.completed method=%s path=%s status=%s duration_ms=%.2f request_id=%s",
                scope.get("method", ""),
                scope.get("path", ""),
                status_code,
                duration_ms,
                request_id,
            )
