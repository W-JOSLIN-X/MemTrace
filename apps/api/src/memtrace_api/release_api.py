"""Day 7 public system, conversation history, and task SSE endpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select

from memtrace_api.conversation_stream import ConversationStreamHub
from memtrace_api.database import session_scope
from memtrace_api.db_models import EventLogModel, MessageModel, TaskModel
from memtrace_api.errors import ApiError, ErrorCode, ErrorEnvelope
from memtrace_api.public_auth import quota_projection
from memtrace_api.release_schemas import (
    ConversationListItem,
    ConversationListResponse,
    SystemResponse,
)
from memtrace_api.repositories import UserContext
from memtrace_api.schemas import EffectiveMemoryMode, ProviderMode
from memtrace_api.session_auth import get_current_user

TASK_ID_PATTERN = r"^task_[0-9A-HJKMNP-TV-Z]{26}$"
router = APIRouter(prefix="/api/v2", tags=["public-release"])


def _require_public(user_ctx: UserContext) -> None:
    if user_ctx.auth_kind != "public":
        raise ApiError(
            status_code=401,
            code=ErrorCode.ACCOUNT_REQUIRED,
            message="该接口需要公开账号会话。",
        )


@router.get("/system", response_model=SystemResponse)
async def system_info(
    request: Request, user_ctx: UserContext = Depends(get_current_user)
) -> SystemResponse:
    _require_public(user_ctx)
    settings = request.app.state.settings
    with session_scope(request.app.state.db_session_factory) as session:
        quota = quota_projection(session, settings, owner_id=user_ctx.user_id)
    return SystemResponse(
        request_id=request.state.request_id,
        version=settings.app_version,
        revision=settings.app_revision,
        migration="007_day7_public_release",
        provider_mode=ProviderMode(settings.provider_mode),
        model=settings.llm_model,
        key_configured=settings.has_llm_api_key,
        memory_budget_per_card=settings.memory_token_budget_per_card,
        memory_budget_total=settings.memory_token_budget_total,
        quota=quota,
    )


@router.get("/tasks", response_model=ConversationListResponse)
async def list_conversations(
    request: Request,
    cursor: str | None = Query(default=None, pattern=TASK_ID_PATTERN),
    limit: int = Query(default=20, ge=1, le=100),
    user_ctx: UserContext = Depends(get_current_user),
) -> ConversationListResponse:
    _require_public(user_ctx)
    with session_scope(request.app.state.db_session_factory) as session:
        query = select(TaskModel).where(
            and_(
                TaskModel.owner_id == user_ctx.user_id,
                TaskModel.status != "deleted",
                TaskModel.next_turn_index > 1,
            )
        )
        if cursor is not None:
            anchor = session.execute(
                select(TaskModel).where(
                    and_(TaskModel.id == cursor, TaskModel.owner_id == user_ctx.user_id)
                )
            ).scalar_one_or_none()
            if anchor is None:
                raise ApiError(
                    status_code=400,
                    code=ErrorCode.INVALID_CURSOR,
                    message="会话游标无效。",
                )
            query = query.where(
                or_(
                    TaskModel.updated_at < anchor.updated_at,
                    and_(TaskModel.updated_at == anchor.updated_at, TaskModel.id > anchor.id),
                )
            )
        tasks = list(
            session.execute(
                query.order_by(TaskModel.updated_at.desc(), TaskModel.id.asc()).limit(limit + 1)
            )
            .scalars()
            .all()
        )
        has_more = len(tasks) > limit
        tasks = tasks[:limit]
        items: list[ConversationListItem] = []
        for task in tasks:
            first_user = session.execute(
                select(MessageModel.content)
                .where(
                    and_(
                        MessageModel.owner_id == user_ctx.user_id,
                        MessageModel.task_id == task.id,
                        MessageModel.role == "user",
                    )
                )
                .order_by(MessageModel.turn_index.asc(), MessageModel.created_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            message_count = session.execute(
                select(func.count())
                .select_from(MessageModel)
                .where(
                    and_(
                        MessageModel.owner_id == user_ctx.user_id,
                        MessageModel.task_id == task.id,
                        MessageModel.turn_index.is_not(None),
                    )
                )
            ).scalar_one()
            title = " ".join((first_user or "新对话").split())[:120] or "新对话"
            items.append(
                ConversationListItem(
                    task_id=task.id,
                    title=title,
                    memory_mode=EffectiveMemoryMode(task.effective_memory_mode),
                    message_count=message_count,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
            )
    return ConversationListResponse(
        request_id=request.state.request_id,
        items=items,
        next_cursor=tasks[-1].id if has_more and tasks else None,
    )


@router.get(
    "/tasks/{task_id}/stream",
    response_class=StreamingResponse,
    responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
)
async def task_stream(
    request: Request,
    task_id: str = Path(pattern=TASK_ID_PATTERN),
    after_event_seq: int = Query(default=0, ge=0),
    user_ctx: UserContext = Depends(get_current_user),
) -> StreamingResponse:
    _require_public(user_ctx)
    factory = request.app.state.db_session_factory
    with session_scope(factory) as session:
        exists = session.execute(
            select(TaskModel.id).where(
                and_(
                    TaskModel.id == task_id,
                    TaskModel.owner_id == user_ctx.user_id,
                    TaskModel.status != "deleted",
                )
            )
        ).scalar_one_or_none()
    if exists is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.TASK_NOT_FOUND,
            message="任务不存在。",
        )
    hub: ConversationStreamHub = request.app.state.conversation_stream_hub
    queue = await hub.subscribe(user_ctx.user_id, task_id)

    async def body() -> AsyncIterator[bytes]:
        cursor = after_event_seq
        try:
            while True:
                rows = _load_events(factory, user_ctx.user_id, task_id, cursor)
                for row in rows:
                    cursor = max(cursor, row.seq)
                    payload = {"event_seq": row.seq, **json.loads(row.metadata_json)}
                    yield _sse(row.event_type, payload, event_id=row.seq)
                try:
                    live = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                event_seq = live.data.get("event_seq")
                if isinstance(event_seq, int) and event_seq <= cursor:
                    continue
                if isinstance(event_seq, int):
                    cursor = event_seq
                yield _sse(
                    live.event_type,
                    live.data,
                    event_id=event_seq if isinstance(event_seq, int) else None,
                )
        finally:
            await hub.unsubscribe(user_ctx.user_id, task_id, queue)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _load_events(factory, owner_id: str, task_id: str, after_seq: int):
    with session_scope(factory) as session:
        return list(
            session.execute(
                select(EventLogModel)
                .where(
                    and_(
                        EventLogModel.owner_id == owner_id,
                        EventLogModel.stream_type == "task",
                        EventLogModel.stream_id == task_id,
                        EventLogModel.seq > after_seq,
                    )
                )
                .order_by(EventLogModel.seq.asc())
                .limit(100)
            )
            .scalars()
            .all()
        )


def _sse(event_type: str, data: dict[str, object], *, event_id: int | None) -> bytes:
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append("data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return ("\n".join(lines) + "\n\n").encode("utf-8")
