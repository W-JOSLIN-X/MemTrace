"""Durable single-consumer worker for Day 3 feedback compilation."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import and_, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from memtrace_api.compiler import (
    ExtractionSchema,
    ProviderFailure,
    StructuredProvider,
    build_structured_provider,
)
from memtrace_api.config import Settings
from memtrace_api.database import session_scope
from memtrace_api.db_models import (
    FeedbackEventModel,
    MemoryCardModel,
    MemoryEvidenceLinkModel,
    MemoryEvidenceModel,
    MemoryJobModel,
    MessageModel,
    TaskFingerprintModel,
)
from memtrace_api.diff import DiffResult, compute_diff
from memtrace_api.durability import Durability, Reason, detect_durability
from memtrace_api.events import (
    EventType,
    MemoryCandidateCreatedPayload,
    MemoryExtractionStagePayload,
    MemoryJobFailedPayload,
)
from memtrace_api.gates import run_all_gates
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.repositories import TaskRepository, UserContext
from memtrace_api.schemas import (
    Disposition,
    MemoryJobErrorCode,
    MemoryJobStage,
    MemoryScope,
    ScopeDomain,
    ScopeLevel,
    TaskFingerprint,
    utc_now,
)
from memtrace_api.store import ReplayCapacityError, TaskMissingError, TaskStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: str
    owner_id: str
    feedback_id: str
    attempt: int


@dataclass(frozen=True, slots=True)
class JobContext:
    job: ClaimedJob
    task_id: str
    run_id: str
    explicit_text: str | None
    edited_output: str | None
    rating: int | None
    accepted: bool | None
    original_output: str | None
    fingerprint: TaskFingerprint


@dataclass(frozen=True, slots=True)
class PersistedEvent:
    owner_id: str
    task_id: str
    event_type: EventType
    event_seq: int
    data: dict[str, Any]


class MemoryJobWorker:
    """Globally claims pending jobs and runs exactly one pipeline at a time."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        store: TaskStore,
        *,
        provider: StructuredProvider | None = None,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._store = store
        self._provider = provider or build_structured_provider(settings)
        self._poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._active_job: ClaimedJob | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._run_loop(), name="memory-job-worker")

    async def stop(self, *, timeout_seconds: float = 5.0) -> None:
        """Stop after a bounded drain; interrupted work remains explicitly retryable."""
        self._running = False
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
            except TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if self._active_job is not None:
                    await asyncio.to_thread(
                        self._fail_job,
                        self._active_job,
                        MemoryJobErrorCode.MEMORY_JOB_INTERRUPTED,
                        True,
                    )
        await self._provider.aclose()

    async def run_once(self) -> bool:
        job = await asyncio.to_thread(self._claim_next_job)
        if job is None:
            return False
        self._active_job = job
        try:
            await self._process_job(job)
        finally:
            self._active_job = None
        return True

    async def _run_loop(self) -> None:
        while self._running:
            try:
                processed = await self.run_once()
                if not processed:
                    await asyncio.sleep(self._poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("memory.worker.loop_failed type=%s", type(exc).__name__)
                await asyncio.sleep(self._poll_interval_seconds)

    def _claim_next_job(self) -> ClaimedJob | None:
        """Use one conditional SQLite update so competing workers cannot double-claim."""
        with session_scope(self._session_factory) as session:
            row = session.execute(
                text(
                    "UPDATE memory_jobs "
                    "SET status='running', stage='queued', attempt=attempt+1, "
                    "retryable=0, last_error_code=NULL, disposition=NULL, updated_at=:now "
                    "WHERE id=(SELECT id FROM memory_jobs WHERE status='pending' "
                    "ORDER BY created_at ASC, id ASC LIMIT 1) "
                    "AND status='pending' "
                    "RETURNING id, owner_id, feedback_id, attempt"
                ),
                {"now": utc_now()},
            ).one_or_none()
            if row is None:
                return None
            return ClaimedJob(
                job_id=row.id,
                owner_id=row.owner_id,
                feedback_id=row.feedback_id,
                attempt=row.attempt,
            )

    async def _process_job(self, job: ClaimedJob) -> None:
        try:
            context = await asyncio.to_thread(self._load_context, job)
            await self._persist_and_broadcast_stage(context, MemoryJobStage.DIFFING)

            diff_result = None
            if context.edited_output is not None and context.original_output is not None:
                diff_result = compute_diff(context.original_output, context.edited_output)

            await self._persist_and_broadcast_stage(
                context,
                MemoryJobStage.CLASSIFYING_DURABILITY,
            )
            durability, reason = detect_durability(
                explicit_text=context.explicit_text,
                edited_output=context.edited_output,
                rating=context.rating,
                accepted=context.accepted,
                has_editable_diff=(
                    diff_result is not None and context.edited_output != context.original_output
                ),
            )

            early_disposition = _early_disposition(durability, reason)
            if early_disposition is not None:
                await self._persist_and_broadcast_stage(context, MemoryJobStage.ADMITTING)
                events = await asyncio.to_thread(
                    self._finish_without_candidates,
                    context,
                    early_disposition,
                    diff_result,
                )
                await self._broadcast_many(events)
                return

            await self._persist_and_broadcast_stage(context, MemoryJobStage.EXTRACTING)
            prompt = self._build_prompt(context, diff_result, durability, reason)
            raw = await self._provider.complete_json(
                prompt,
                ExtractionSchema.model_json_schema(),
            )

            await self._persist_and_broadcast_stage(context, MemoryJobStage.VALIDATING)
            try:
                extracted = ExtractionSchema.model_validate(raw)
            except ValidationError:
                repair_prompt = self._build_repair_prompt(context, raw)
                try:
                    repaired = await self._provider.complete_json(
                        repair_prompt,
                        ExtractionSchema.model_json_schema(),
                    )
                    extracted = ExtractionSchema.model_validate(repaired)
                except (ProviderFailure, ValidationError) as exc:
                    raise ProviderFailure("MEMORY_REPAIR_FAILED", retryable=False) from exc

            await self._persist_and_broadcast_stage(context, MemoryJobStage.ADMITTING)
            candidates = self._admitted_candidates(
                context,
                extracted,
                durability,
            )
            events = await asyncio.to_thread(
                self._finish_with_candidates,
                context,
                candidates,
                diff_result,
            )
            await self._broadcast_many(events)
        except asyncio.CancelledError:
            raise
        except ProviderFailure as exc:
            error_code = _provider_error_code(exc.code)
            events = await asyncio.to_thread(self._fail_job, job, error_code, exc.retryable)
            await self._broadcast_many(events)
        except Exception as exc:
            logger.error(
                "memory.job.failed job_id=%s type=%s",
                job.job_id,
                type(exc).__name__,
            )
            events = await asyncio.to_thread(
                self._fail_job,
                job,
                MemoryJobErrorCode.MEMORY_SCHEMA_INVALID,
                False,
            )
            await self._broadcast_many(events)

    def _load_context(self, job: ClaimedJob) -> JobContext:
        with session_scope(self._session_factory) as session:
            persisted_job = session.execute(
                select(MemoryJobModel).where(
                    and_(
                        MemoryJobModel.id == job.job_id,
                        MemoryJobModel.owner_id == job.owner_id,
                    )
                )
            ).scalar_one_or_none()
            if persisted_job is None or persisted_job.status != "running":
                raise ValueError("claimed job is no longer running")
            feedback = session.execute(
                select(FeedbackEventModel).where(
                    and_(
                        FeedbackEventModel.id == job.feedback_id,
                        FeedbackEventModel.owner_id == job.owner_id,
                    )
                )
            ).scalar_one_or_none()
            if feedback is None:
                raise ValueError("feedback is missing")
            fingerprint_row = session.execute(
                select(TaskFingerprintModel).where(
                    and_(
                        TaskFingerprintModel.task_id == feedback.task_id,
                        TaskFingerprintModel.owner_id == job.owner_id,
                    )
                )
            ).scalar_one_or_none()
            if fingerprint_row is None:
                raise ValueError("task fingerprint is missing")
            assistant = (
                session.execute(
                    select(MessageModel)
                    .where(
                        and_(
                            MessageModel.owner_id == job.owner_id,
                            MessageModel.task_id == feedback.task_id,
                            MessageModel.run_id == feedback.run_id,
                            MessageModel.role == "assistant",
                        )
                    )
                    .order_by(MessageModel.created_at.desc())
                )
                .scalars()
                .first()
            )
            return JobContext(
                job=job,
                task_id=feedback.task_id,
                run_id=feedback.run_id,
                explicit_text=feedback.explicit_text,
                edited_output=feedback.edited_output,
                rating=feedback.rating,
                accepted=feedback.accepted,
                original_output=assistant.content if assistant is not None else None,
                fingerprint=TaskFingerprint.model_validate_json(fingerprint_row.fingerprint_json),
            )

    async def _persist_and_broadcast_stage(
        self,
        context: JobContext,
        stage: MemoryJobStage,
    ) -> None:
        event = await asyncio.to_thread(self._persist_stage, context, stage)
        await self._broadcast(event)

    def _persist_stage(self, context: JobContext, stage: MemoryJobStage) -> PersistedEvent:
        with session_scope(self._session_factory) as session:
            changed = session.execute(
                update(MemoryJobModel)
                .where(
                    and_(
                        MemoryJobModel.id == context.job.job_id,
                        MemoryJobModel.owner_id == context.job.owner_id,
                        MemoryJobModel.status == "running",
                    )
                )
                .values(stage=stage.value, updated_at=utc_now())
            ).rowcount
            if changed != 1:
                raise ValueError("memory job stage transition lost ownership")
            user_ctx = UserContext(context.job.owner_id, "memory_worker")
            task_repo = TaskRepository(user_ctx, session)
            data = MemoryExtractionStagePayload(
                memory_job_id=context.job.job_id,
                stage=stage,
            ).model_dump(mode="json")
            seq = task_repo.allocate_next_event_seq(context.task_id)
            task_repo.append_event(
                stream_type="task",
                stream_id=context.task_id,
                seq=seq,
                event_type=EventType.MEMORY_EXTRACTION_STAGE.value,
                metadata=data,
            )
            return PersistedEvent(
                context.job.owner_id,
                context.task_id,
                EventType.MEMORY_EXTRACTION_STAGE,
                seq,
                data,
            )

    def _admitted_candidates(
        self,
        context: JobContext,
        extracted: ExtractionSchema,
        durability: Durability,
    ) -> list[dict[str, Any]]:
        scope = _canonical_scope(context.fingerprint).model_dump(mode="json")
        accepted: list[dict[str, Any]] = []
        for index, candidate_model in enumerate(extracted.candidates):
            candidate = candidate_model.model_dump(mode="json")
            candidate["scope"] = scope
            candidate["save_preselected"] = durability is Durability.EXPLICIT_DURABLE
            result = run_all_gates(
                candidate=candidate,
                durability=durability.value,
                feedback_text=context.explicit_text,
                edited_output=context.edited_output,
                fingerprint=context.fingerprint,
                candidate_index=index,
            )
            if result.all_passed:
                accepted.append(candidate)
            else:
                logger.info(
                    "memory.candidate.blocked job_id=%s ordinal=%d gate=%s reason=%s",
                    context.job.job_id,
                    index,
                    result.blocking_gate,
                    result.final_decision.reason,
                )
        return accepted[:3]

    def _finish_with_candidates(
        self,
        context: JobContext,
        candidates: list[dict[str, Any]],
        diff_result: DiffResult | None,
    ) -> list[PersistedEvent]:
        if not candidates:
            return self._finish_without_candidates(
                context,
                Disposition.NO_MEMORY,
                diff_result,
            )
        events: list[PersistedEvent] = []
        with session_scope(self._session_factory) as session:
            job = _running_job(session, context.job)
            user_ctx = UserContext(context.job.owner_id, "memory_worker")
            task_repo = TaskRepository(user_ctx, session)
            for ordinal, candidate in enumerate(candidates):
                memory_id = new_prefixed_ulid("mem")
                evidence_id = new_prefixed_ulid("evidence")
                scope = candidate["scope"]
                source_type, source_field = _source_projection(candidate["evidence_source"])
                now = utc_now()
                card = MemoryCardModel(
                    id=memory_id,
                    owner_id=context.job.owner_id,
                    memory_job_id=context.job.job_id,
                    current_version_id=None,
                    status="candidate",
                    kind=candidate["kind"],
                    source_type=source_type,
                    save_preselected=bool(candidate["save_preselected"]),
                    rejection_reason=None,
                    title=candidate["title"],
                    rule=candidate["rule"],
                    avoid=candidate["avoid"],
                    trigger_text=candidate["trigger_text"],
                    scope_level=scope["level"],
                    domain=scope["domain"],
                    task_type=scope.get("task_type"),
                    artifact_type=scope.get("artifact_type"),
                    audience=scope.get("audience"),
                    project_key=scope.get("project_key"),
                    scope_json=json.dumps(scope, separators=(",", ":"), ensure_ascii=False),
                    exceptions_json=json.dumps(
                        candidate["exceptions"], separators=(",", ":"), ensure_ascii=False
                    ),
                    source_trust=1.0 if source_type == "explicit_feedback" else 0.8,
                    rule_confidence=None,
                    scope_confidence=None,
                    evidence_count=1,
                    version=0,
                    valid_from=None,
                    valid_to=None,
                    created_at=now,
                    updated_at=now,
                )
                evidence = MemoryEvidenceModel(
                    id=evidence_id,
                    owner_id=context.job.owner_id,
                    feedback_id=context.job.feedback_id,
                    task_id=context.task_id,
                    run_id=context.run_id,
                    memory_job_id=context.job.job_id,
                    source_type=source_type,
                    source_field=source_field,
                    evidence_quote=candidate["evidence_quote"],
                    diff_summary_json=_diff_summary_json(diff_result),
                    normalized_edit_cost=(
                        diff_result.normalized_edit_cost if diff_result is not None else None
                    ),
                    episode_summary=None,
                    disposition=Disposition.CANDIDATE_CREATED.value,
                    created_at=now,
                )
                link = MemoryEvidenceLinkModel(
                    id=new_prefixed_ulid("evidlink"),
                    owner_id=context.job.owner_id,
                    memory_id=memory_id,
                    evidence_id=evidence_id,
                    ordinal=ordinal,
                    created_at=now,
                )
                session.add_all([card, evidence, link])
                session.flush()
                data = MemoryCandidateCreatedPayload(
                    memory_job_id=context.job.job_id,
                    memory_id=memory_id,
                    evidence_id=evidence_id,
                    ordinal=ordinal,
                ).model_dump(mode="json")
                seq = task_repo.allocate_next_event_seq(context.task_id)
                task_repo.append_event(
                    stream_type="task",
                    stream_id=context.task_id,
                    seq=seq,
                    event_type=EventType.MEMORY_CANDIDATE_CREATED.value,
                    metadata=data,
                )
                events.append(
                    PersistedEvent(
                        context.job.owner_id,
                        context.task_id,
                        EventType.MEMORY_CANDIDATE_CREATED,
                        seq,
                        data,
                    )
                )

            job.status = "completed"
            job.stage = MemoryJobStage.DONE.value
            job.disposition = Disposition.CANDIDATE_CREATED.value
            job.last_error_code = None
            job.retryable = False
            job.updated_at = utc_now()
            events.append(_append_done_event(task_repo, context))
        return events

    def _finish_without_candidates(
        self,
        context: JobContext,
        disposition: Disposition,
        diff_result: DiffResult | None,
    ) -> list[PersistedEvent]:
        with session_scope(self._session_factory) as session:
            job = _running_job(session, context.job)
            if disposition is Disposition.EPISODE_ONLY:
                source = context.explicit_text or context.edited_output
                if source:
                    source_type, source_field = _source_projection(
                        "explicit_text" if context.explicit_text else "edit_diff"
                    )
                    session.add(
                        MemoryEvidenceModel(
                            id=new_prefixed_ulid("evidence"),
                            owner_id=context.job.owner_id,
                            feedback_id=context.job.feedback_id,
                            task_id=context.task_id,
                            run_id=context.run_id,
                            memory_job_id=context.job.job_id,
                            source_type=source_type,
                            source_field=source_field,
                            evidence_quote=source[:2_000],
                            diff_summary_json=_diff_summary_json(diff_result),
                            normalized_edit_cost=(
                                diff_result.normalized_edit_cost
                                if diff_result is not None
                                else None
                            ),
                            episode_summary="one_shot_feedback",
                            disposition=Disposition.EPISODE_ONLY.value,
                            created_at=utc_now(),
                        )
                    )
            job.status = "completed"
            job.stage = MemoryJobStage.DONE.value
            job.disposition = disposition.value
            job.last_error_code = None
            job.retryable = False
            job.updated_at = utc_now()
            task_repo = TaskRepository(
                UserContext(context.job.owner_id, "memory_worker"),
                session,
            )
            return [_append_done_event(task_repo, context)]

    def _fail_job(
        self,
        job: ClaimedJob,
        error_code: MemoryJobErrorCode,
        retryable: bool,
    ) -> list[PersistedEvent]:
        with session_scope(self._session_factory) as session:
            persisted = session.execute(
                select(MemoryJobModel).where(
                    and_(
                        MemoryJobModel.id == job.job_id,
                        MemoryJobModel.owner_id == job.owner_id,
                    )
                )
            ).scalar_one_or_none()
            if persisted is None or persisted.status not in {"running", "pending"}:
                return []
            feedback = session.execute(
                select(FeedbackEventModel).where(
                    and_(
                        FeedbackEventModel.id == job.feedback_id,
                        FeedbackEventModel.owner_id == job.owner_id,
                    )
                )
            ).scalar_one()
            persisted.status = "failed"
            persisted.stage = MemoryJobStage.FAILED.value
            persisted.last_error_code = error_code.value
            persisted.retryable = retryable
            persisted.disposition = Disposition.FAILED.value
            persisted.updated_at = utc_now()
            task_repo = TaskRepository(UserContext(job.owner_id, "memory_worker"), session)
            data = MemoryJobFailedPayload(
                memory_job_id=job.job_id,
                stage=MemoryJobStage.FAILED,
                error_code=error_code,
                retryable=retryable,
            ).model_dump(mode="json")
            seq = task_repo.allocate_next_event_seq(feedback.task_id)
            task_repo.append_event(
                stream_type="task",
                stream_id=feedback.task_id,
                seq=seq,
                event_type=EventType.MEMORY_JOB_FAILED.value,
                metadata=data,
            )
            return [
                PersistedEvent(
                    job.owner_id,
                    feedback.task_id,
                    EventType.MEMORY_JOB_FAILED,
                    seq,
                    data,
                )
            ]

    def _build_prompt(
        self,
        context: JobContext,
        diff_result: DiffResult | None,
        durability: Durability,
        reason: Reason,
    ) -> str:
        payload = {
            "explicit_text": context.explicit_text,
            "edited_output": (
                context.edited_output[:4_000] if context.edited_output is not None else None
            ),
            "original_output": (
                context.original_output[:4_000] if context.original_output is not None else None
            ),
            "diff_summary": (
                json.loads(_diff_summary_json(diff_result)) if diff_result is not None else None
            ),
            "durability": durability.value,
            "durability_reason": reason.value,
            "fingerprint": {
                "domain": context.fingerprint.domain.value,
                "task_type": context.fingerprint.task_type.value,
                "artifact_type": context.fingerprint.artifact_type.value,
                "audience": context.fingerprint.audience.value,
                "classification_confidence": context.fingerprint.classification_confidence,
            },
        }
        return (
            "Extract zero to three atomic, reusable candidate memories. "
            "Never broaden scope beyond the supplied fingerprint and quote exact user evidence.\n"
            "MEMTRACE_CONTEXT_JSON:"
            + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        )

    def _build_repair_prompt(self, context: JobContext, raw: dict[str, Any]) -> str:
        repair_context = {
            "explicit_text": context.explicit_text,
            "edited_output": context.edited_output[:4_000] if context.edited_output else None,
            "previous_output": raw,
        }
        return (
            "Repair the previous output to exactly match the supplied JSON Schema.\n"
            "MEMTRACE_CONTEXT_JSON:"
            + json.dumps(repair_context, separators=(",", ":"), ensure_ascii=False)
        )

    async def _broadcast_many(self, events: list[PersistedEvent]) -> None:
        for event in events:
            await self._broadcast(event)

    async def _broadcast(self, event: PersistedEvent) -> None:
        try:
            record = await self._store.get(event.task_id)
            if record.user_ctx is not None and record.user_ctx.user_id != event.owner_id:
                return
            await self._store.emit_preallocated_persistent(
                record,
                event_type=event.event_type,
                event_seq=event.event_seq,
                data=event.data,
            )
        except (TaskMissingError, ReplayCapacityError):
            return


def _running_job(session: Session, job: ClaimedJob) -> MemoryJobModel:
    persisted = session.execute(
        select(MemoryJobModel).where(
            and_(
                MemoryJobModel.id == job.job_id,
                MemoryJobModel.owner_id == job.owner_id,
                MemoryJobModel.status == "running",
            )
        )
    ).scalar_one_or_none()
    if persisted is None:
        raise ValueError("memory job is no longer running")
    return persisted


def _canonical_scope(fingerprint: TaskFingerprint) -> MemoryScope:
    if fingerprint.domain.value == "other" or fingerprint.classification_confidence < 0.70:
        return MemoryScope(level=ScopeLevel.SESSION, domain=ScopeDomain.OTHER)
    return MemoryScope(
        level=ScopeLevel.TASK_FAMILY,
        domain=ScopeDomain(fingerprint.domain.value),
        task_type=fingerprint.task_type,
        artifact_type=fingerprint.artifact_type,
        audience=fingerprint.audience,
    )


def _early_disposition(durability: Durability, reason: Reason) -> Disposition | None:
    if durability is Durability.ONE_SHOT:
        return Disposition.EPISODE_ONLY
    if durability is Durability.REINFORCE_USAGE_ONLY:
        return Disposition.REINFORCE_USAGE_ONLY
    if durability is Durability.HARMFUL_USAGE_ONLY:
        return Disposition.NO_MEMORY
    if durability is Durability.AMBIGUOUS and reason is not Reason.EDIT_DIFF_ONLY:
        return Disposition.NO_MEMORY
    return None


def _source_projection(source: str) -> tuple[str, str]:
    if source == "explicit_text":
        return "explicit_feedback", "explicit_text"
    return "edit_diff", "edited_output"


def _diff_summary_json(diff_result: DiffResult | None) -> str | None:
    if diff_result is None:
        return None
    return json.dumps(
        {
            "hunk_count": diff_result.hunk_count,
            "added_chars": diff_result.added_chars,
            "removed_chars": diff_result.removed_chars,
            "original_len": diff_result.original_len,
            "edited_len": diff_result.edited_len,
            "truncated": diff_result.truncated,
        },
        separators=(",", ":"),
    )


def _append_done_event(
    task_repo: TaskRepository,
    context: JobContext,
) -> PersistedEvent:
    data = MemoryExtractionStagePayload(
        memory_job_id=context.job.job_id,
        stage=MemoryJobStage.DONE,
    ).model_dump(mode="json")
    seq = task_repo.allocate_next_event_seq(context.task_id)
    task_repo.append_event(
        stream_type="task",
        stream_id=context.task_id,
        seq=seq,
        event_type=EventType.MEMORY_EXTRACTION_STAGE.value,
        metadata=data,
    )
    return PersistedEvent(
        context.job.owner_id,
        context.task_id,
        EventType.MEMORY_EXTRACTION_STAGE,
        seq,
        data,
    )


def _provider_error_code(code: str) -> MemoryJobErrorCode:
    try:
        return MemoryJobErrorCode(code)
    except ValueError:
        return MemoryJobErrorCode.MEMORY_PROVIDER_ERROR


def recover_stale_jobs(session_factory: sessionmaker[Session]) -> int:
    """Mark every prior-process running job interrupted and append a durable event."""
    with session_scope(session_factory) as session:
        rows = list(
            session.execute(
                select(MemoryJobModel, FeedbackEventModel)
                .join(FeedbackEventModel, FeedbackEventModel.id == MemoryJobModel.feedback_id)
                .where(MemoryJobModel.status == "running")
                .order_by(MemoryJobModel.created_at.asc(), MemoryJobModel.id.asc())
            ).all()
        )
        for job, feedback in rows:
            job.status = "failed"
            job.stage = MemoryJobStage.FAILED.value
            job.last_error_code = MemoryJobErrorCode.MEMORY_JOB_INTERRUPTED.value
            job.retryable = True
            job.disposition = Disposition.FAILED.value
            job.updated_at = utc_now()
            task_repo = TaskRepository(UserContext(job.owner_id, "memory_worker"), session)
            data = MemoryJobFailedPayload(
                memory_job_id=job.id,
                stage=MemoryJobStage.FAILED,
                error_code=MemoryJobErrorCode.MEMORY_JOB_INTERRUPTED,
                retryable=True,
            ).model_dump(mode="json")
            seq = task_repo.allocate_next_event_seq(feedback.task_id)
            task_repo.append_event(
                stream_type="task",
                stream_id=feedback.task_id,
                seq=seq,
                event_type=EventType.MEMORY_JOB_FAILED.value,
                metadata=data,
            )
        return len(rows)
