"""ASGI middleware that remains safe when streaming responses are added."""

from __future__ import annotations

import json
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


class RequestBodyTooLarge(Exception):
    pass


class SecurityHeadersMiddleware:
    """Streaming-safe request-size enforcement and release security headers."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_request_body_bytes: int,
        enable_hsts: bool = False,
    ) -> None:
        self.app = app
        self.max_request_body_bytes = max_request_body_bytes
        self.enable_hsts = enable_hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", ())}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > self.max_request_body_bytes:
                    await self._too_large(scope, receive, send)
                    return
            except ValueError:
                await self._too_large(scope, receive, send)
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_request_body_bytes:
                    raise RequestBodyTooLarge
            return message

        async def secure_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["X-Frame-Options"] = "DENY"
                response_headers["Referrer-Policy"] = "no-referrer"
                response_headers["Permissions-Policy"] = (
                    "camera=(), microphone=(), geolocation=(), payment=()"
                )
                response_headers["Content-Security-Policy"] = (
                    "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
                    "form-action 'self'; img-src 'self' data:; style-src 'self'; "
                    "script-src 'self'; connect-src 'self'"
                )
                if self.enable_hsts:
                    response_headers["Strict-Transport-Security"] = (
                        "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        try:
            await self.app(scope, limited_receive, secure_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await self._too_large(scope, receive, secure_send)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        del receive
        request_id = scope.get("state", {}).get("request_id", "req_unknown")
        content = build_error_content(
            request_id=request_id,
            code=ErrorCode.VALIDATION_ERROR,
            message="请求体超过允许上限。",
        )
        body = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
