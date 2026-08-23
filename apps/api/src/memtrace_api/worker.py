"""Day 3 G2: Single asyncio memory-job worker with startup recovery.

The worker claims pending jobs atomically via ``UPDATE ... WHERE status='pending'
... RETURNING`` so no two workers ever process the same job.

Startup recovery:
- Stale ``running`` jobs from a previous process → ``failed`` with
  ``MEMORY_JOB_INTERRUPTED``.
- ``pending`` jobs → left for the worker to claim normally.

All DB calls are wrapped via ``asyncio.to_thread`` to keep the async loop
responsive.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from memtrace_api.config import Settings
from memtrace_api.db_models import MemoryJobModel
from memtrace_api.diff import compute_diff
from memtrace_api.durability import detect_durability
from memtrace_api.events import (
    EventType,
    MemoryCandidateCreatedPayload,
    MemoryExtractionStagePayload,
    MemoryJobFailedPayload,
)
from memtrace_api.gates import run_all_gates
from memtrace_api.providers import ProviderMode
from memtrace_api.repositories import (
    FeedbackRepository,
    MemoryJobRepository,
    TaskRepository,
    UserContext,
)
from memtrace_api.schemas import (
    AsyncErrorCode,
    Disposition,
    MemoryJobErrorCode,
    MemoryJobStage,
    ProviderMode,
    utc_now,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class MemoryJobWorker:
    """Single asyncio worker that processes pending memory jobs.

    One instance per API process.  The worker:
    1. Atomically claims one pending job at a time (no race).
    2. Runs the full extraction pipeline (diff → durability → provider → validate → insert).
    3. Commits the result and marks the job ``completed``, or marks it ``failed``.
    4. Sleeps 1 s when no work is available.
    """

    def __init__(
        self,
        session_factory: Any,
        user_ctx: UserContext,
        settings: Settings,
        store: Any,
    ) -> None:
        self._session_factory = session_factory
        self._user_ctx = user_ctx
        self._settings = settings
        self._store = store
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def start(self) -> None:
        """Start the worker loop in the current event loop."""
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        """Signal the worker to stop and cancel its task."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Claim → process → repeat until stopped."""
        while self._running:
            try:
                job = await asyncio.to_thread(self._claim_next_job)
                if job is None:
                    await asyncio.sleep(1.0)
                    continue
                await self._process_job(job)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("worker loop error")
                await asyncio.sleep(5.0)

    # ------------------------------------------------------------------
    # Job claim
    # ------------------------------------------------------------------

    def _claim_next_job(self) -> MemoryJobModel | None:
        """Atomically claim one pending job via ``UPDATE ... RETURNING``.

        Returns the job model, or ``None`` if no pending jobs exist.
        The caller must not hold any other DB write lock when calling this.
        """
        with session_scope(self._session_factory) as session:
            result = session.execute(
                text(
                    "UPDATE memory_jobs "
                    "SET status = 'running', "
                    "    stage = 'diffing', "
                    "    attempt = attempt + 1, "
                    "    updated_at = :now "
                    "WHERE id = ("
                    "  SELECT id FROM memory_jobs "
                    "  WHERE owner_id = :owner "
                    "    AND status = 'pending' "
                    "  ORDER BY created_at ASC "
                    "  LIMIT 1"
                    ") "
                    "RETURNING *"
                ),
                {"owner": self._user_ctx.user_id, "now": utc_now()},
            ).fetchone()

            if result is None:
                session.commit()
                return None

            job = MemoryJobModel(**dict(result._mapping))
            session.commit()
            return job

    # ------------------------------------------------------------------
    # Job processing
    # ------------------------------------------------------------------

    async def _process_job(self, job: MemoryJobModel) -> None:
        """Run the full extraction pipeline for *job*."""
        logger.info("Processing memory job %s", job.id)
        await self._emit_stage_event(job, MemoryJobStage.DIFFING)

        try:
            with session_scope(self._session_factory) as session:
                fb_repo = FeedbackRepository(self._user_ctx, session)
                task_repo = TaskRepository(self._user_ctx, session)

                # --- Load inputs ---
                feedback = fb_repo.get_feedback(job.feedback_id)
                if feedback is None:
                    raise ValueError(f"Feedback {job.feedback_id} not found")

                original_output = ""
                edited_output = feedback.edited_output
                task_snapshot = task_repo.get_snapshot(feedback.task_id)
                if task_snapshot and task_snapshot.final_message:
                    original_output = task_snapshot.final_message.content

                # --- Step 1: Diff ---
                diff_result = compute_diff(
                    original_output,
                    edited_output or "",
                )
                await self._emit_stage_event(job, MemoryJobStage.CLASSIFYING_DURABILITY)

                # --- Step 2: Durability ---
                has_edit_diff = bool(feedback.edited_output and original_output)
                durability, reason = detect_durability(
                    explicit_text=feedback.explicit_text,
                    edited_output=feedback.edited_output,
                    rating=feedback.rating,
                    accepted=feedback.accepted,
                    has_editable_diff=has_edit_diff,
                )

                # --- Early dispositions (no provider needed) ---
                if durability == "ambiguous" and reason == "one_shot_marker_found":
                    self._finish_job(
                        session, job, Disposition.EPISODE_ONLY, [], fb_repo, task_repo
                    )
                    return
                if durability == "reinforce_usage_only":
                    self._finish_job(
                        session, job, Disposition.REINFORCE_USAGE_ONLY, [], fb_repo, task_repo
                    )
                    return
                if durability == "harmful_usage_only":
                    self._finish_job(
                        session, job, Disposition.NO_MEMORY, [], fb_repo, task_repo
                    )
                    return
                if durability == "ambiguous" and not feedback.explicit_text:
                    self._finish_job(
                        session, job, Disposition.NO_MEMORY, [], fb_repo, task_repo
                    )
                    return

                await self._emit_stage_event(job, MemoryJobStage.EXTRACTING)

                # --- Step 3: Provider ---
                from memtrace_api.compiler import (
                    ExtractionSchema,
                    MockStructuredProvider,
                    ProviderFailure,
                    build_structured_provider,
                )

                provider = build_structured_provider(self._settings)
                prompt = self._build_prompt(
                    feedback, original_output, diff_result, (durability, reason)
                )
                simulation = None  # fixture simulation key, if any

                try:
                    raw = await provider.complete_json(
                        prompt, output_schema={}, simulation=simulation
                    )
                except ProviderFailure as exc:
                    self._mark_failed(
                        session, job,
                        MemoryJobErrorCode.MEMORY_PROVIDER_ERROR,
                        exc.retryable,
                    )
                    return
                except Exception as exc:
                    self._mark_failed(
                        session, job,
                        MemoryJobErrorCode.MEMORY_PROVIDER_ERROR,
                        True,
                    )
                    logger.warning("Provider error: %s", exc)
                    return

                # --- Step 4: Validate (with one repair retry) ---
                try:
                    extracted = ExtractionSchema.model_validate(raw)
                except Exception:
                    repair_prompt = (
                        "Your previous output did not match the required schema. "
                        "Please fix it and output valid JSON.\n"
                        f"Schema:\n{json.dumps(ExtractionSchema.model_json_schema(), ensure_ascii=False)}\n"
                        f"Your output:\n{json.dumps(raw, ensure_ascii=False)}"
                    )
                    try:
                        repaired = await provider.complete_json(
                            repair_prompt, output_schema={}, simulation=simulation
                        )
                        extracted = ExtractionSchema.model_validate(repaired)
                    except Exception:
                        self._mark_failed(
                            session, job,
                            MemoryJobErrorCode.MEMORY_REPAIR_FAILED,
                            False,
                        )
                        return

                await self._emit_stage_event(job, MemoryJobStage.VALIDATING)

                # --- Step 5: Run P0 Gates ---
                candidate_dicts = self._map_candidates(
                    extracted, feedback, diff_result, (durability, reason)
                )
                accepted_candidates, blocked_details = self._apply_gates(
                    candidate_dicts, durability, feedback
                )

                # --- Step 6: Insert candidates + evidence + events ---
                candidate_ids = self._insert_candidates(
                    session, job, feedback, accepted_candidates, fb_repo, task_repo
                )

                # --- Finish ---
                job_repo = MemoryJobRepository(self._user_ctx, session)
                job_repo.complete_job(
                    job_id=job.id,
                    disposition=(
                        Disposition.CANDIDATE_CREATED
                        if candidate_ids
                        else Disposition.NO_MEMORY
                    ),
                    candidate_ids=candidate_ids,
                )
                session.commit()
                await self._emit_stage_event(job, MemoryJobStage.DONE)

        except Exception as exc:
            logger.exception("Job %s failed: %s", job.id, exc)
            try:
                with session_scope(self._session_factory) as session:
                    self._mark_failed(
                        session, job,
                        MemoryJobErrorCode.MEMORY_PROVIDER_ERROR,
                        True,
                    )
            except Exception:
                logger.exception("Failed to mark job %s as failed", job.id)

    # ------------------------------------------------------------------
    # Job completion helpers
    # ------------------------------------------------------------------

    def _finish_job(
        self,
        session: Session,
        job: MemoryJobModel,
        disposition: Disposition,
        candidate_ids: list[str],
        fb_repo: Any,
        task_repo: Any,
    ) -> None:
        job_repo = MemoryJobRepository(self._user_ctx, session)
        job_repo.complete_job(
            job_id=job.id,
            disposition=disposition,
            candidate_ids=candidate_ids,
        )
        session.commit()

    def _mark_failed(
        self,
        session: Session,
        job: MemoryJobModel,
        error_code: MemoryJobErrorCode,
        retryable: bool,
    ) -> None:
        job_repo = MemoryJobRepository(self._user_ctx, session)
        job_repo.fail_job(job_id=job.id, error_code=error_code, retryable=retryable)
        session.commit()

        # Emit memory.job.failed event
        try:
            payload = MemoryJobFailedPayload(
                memory_job_id=job.id,
                stage=MemoryJobStage.FAILED,
                error_code=error_code,
                retryable=retryable,
            )
            task_repo = TaskRepository(self._user_ctx, session)
            # We need the task_id; use feedback_id as approximate stream id
            task_repo.append_event(
                stream_type="task",
                stream_id=job.feedback_id,
                event_type=EventType.MEMORY_JOB_FAILED,
                data=payload.model_dump(mode="json"),
            )
        except Exception:
            logger.exception("Failed to emit job failed event for %s", job.id)

    async def _emit_stage_event(
        self, job: MemoryJobModel, stage: MemoryJobStage
    ) -> None:
        """Update the job stage in DB and emit the SSE event."""
        try:
            with session_scope(self._session_factory) as session:
                job_repo = MemoryJobRepository(self._user_ctx, session)
                job_repo.update_stage(job_id=job.id, stage=stage)
                session.commit()

            payload = MemoryExtractionStagePayload(
                memory_job_id=job.id, stage=stage
            )
            try:
                with session_scope(self._session_factory) as session:
                    task_repo = TaskRepository(self._user_ctx, session)
                    task_repo.append_event(
                        stream_type="task",
                        stream_id=job.feedback_id,
                        event_type=EventType.MEMORY_EXTRACTION_STAGE,
                        data=payload.model_dump(mode="json"),
                    )
            except Exception:
                pass
        except Exception:
            logger.exception("Failed to emit stage event for %s", job.id)

    # ------------------------------------------------------------------
    # Prompt / mapping / insertion
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        feedback: Any,
        original: str,
        diff_result: Any,
        durability: tuple,
    ) -> str:
        """Build the extraction prompt for the provider."""
        parts = []
        parts.append(f"Feedback: {feedback.explicit_text or '(edit only)'}")
        if original:
            parts.append(f"Original output:\n{original[:4_000]}")
        if diff_result.hunk_count > 0:
            parts.append(f"Diff: {diff_result.change_summary}")
            if not diff_result.truncated:
                parts.append(diff_result.changed_fragment)
        parts.append(
            f"\n[Hard constraint] Durability: {durability[0]} ({durability[1]})"
        )
        parts.append(
            "\nExtract 0-3 candidate memory cards as JSON. "
            "Schema: {\n"
            '  "schema_version": "1.0",\n'
            '  "feedback_summary": "brief summary",\n'
            '  "durability": "explicit_durable|one_shot|ambiguous|reinforce_usage_only|harmful_usage_only",\n'
            '  "disposition": "candidate_created|episode_only|reinforce_usage_only|no_memory|failed",\n'
            '  "candidates": [\n'
            '    {\n'
            '      "category": "preference|rule|experience|one_shot",\n'
            '      "kind": "preference|constraint|procedure|experience",\n'
            '      "title": "4-40 chars",\n'
            '      "rule": "20-300 chars",\n'
            '      "avoid": "optional",\n'
            '      "trigger_text": "optional",\n'
            '      "scope": {"level": "task_family", "domain": "programming_learning"},\n'
            '      "exceptions": [],\n'
            '      "evidence_source": "explicit_text|edit_diff",\n'
            '      "evidence_quote": "exact substring from feedback"\n'
            "    }\n"
            "  ]\n"
            "}"
        )
        return "\n\n".join(parts)

    def _map_candidates(
        self,
        extracted: Any,
        feedback: Any,
        diff_result: Any,
        durability: tuple,
    ) -> list[dict[str, Any]]:
        if not extracted.candidates:
            return []
        return [
            {
                "category": card.category,
                "kind": card.kind,
                "title": card.title,
                "rule": card.rule,
                "avoid": card.avoid,
                "trigger_text": card.trigger_text,
                "scope": card.scope,
                "exceptions": card.exceptions,
                "evidence_source": card.evidence_source,
                "evidence_quote": card.evidence_quote,
                "save_preselected": str(durability[0]) == "explicit_durable",
            }
            for card in extracted.candidates
        ]

    def _apply_gates(
        self,
        candidates: list[dict],
        durability: tuple,
        feedback: Any,
    ) -> tuple[list[dict], list[dict]]:
        """Run P0 gates on each candidate.

        Returns (accepted_candidates, blocked_candidates_with_reasons).
        Gates that block a candidate mark it with ``_gate_blocked`` metadata
        but do not raise — we skip blocked candidates and log the reason.
        """
        from memtrace_api.gates import run_all_gates

        accepted: list[dict] = []
        blocked: list[dict] = []

        for idx, c in enumerate(candidates):
            result = run_all_gates(
                candidate=c,
                durability=durability[0],
                feedback_text=feedback.explicit_text,
                edited_output=feedback.edited_output,
                fingerprint=None,
                candidate_index=idx,
            )
            if result.all_passed:
                accepted.append(c)
            else:
                blocking = result.blocking_gate or "unknown"
                c["_gate_blocked"] = blocking
                c["_gate_detail"] = result.final_decision.detail
                blocked.append(c)
                logger.info(
                    "Gate blocked candidate %d: %s — %s",
                    idx,
                    blocking,
                    result.final_decision.detail,
                )

        return accepted, blocked

    def _insert_candidates(
        self,
        session: Session,
        job: MemoryJobModel,
        feedback: Any,
        candidates: list[dict],
        fb_repo: Any,
        task_repo: Any,
    ) -> list[str]:
        """Insert candidates + evidence + evidence links + events atomically."""
        from memtrace_api.ids import new_prefixed_ulid

        candidate_ids: list[str] = []
        for i, c in enumerate(candidates[:3]):
            memory_id = new_prefixed_ulid("mem")
            evidence_id = new_prefixed_ulid("evidence")

            # Evidence row
            session.execute(
                text(
                    "INSERT INTO memory_evidence "
                    "(id, owner_id, feedback_id, task_id, run_id, memory_job_id, "
                    " source_type, source_field, evidence_quote, episode_summary, "
                    " diff_summary_json, normalized_edit_cost, created_at) "
                    "VALUES (:id, :owner, :fb, :task, :run, :job, "
                    "        :src, :field, :quote, :summary, "
                    "        :diff, :cost, :now)"
                ),
                {
                    "id": evidence_id,
                    "owner": self._user_ctx.user_id,
                    "fb": feedback.id,
                    "task": feedback.task_id,
                    "run": feedback.run_id,
                    "job": job.id,
                    "src": c["evidence_source"],
                    "field": (
                        "explicit_text"
                        if c["evidence_source"] == "explicit_text"
                        else "edited_output"
                    ),
                    "quote": c["evidence_quote"][:2_000],
                    "summary": None,
                    "diff": None,
                    "cost": None,
                    "now": utc_now(),
                },
            )

            # Candidate card (status = candidate, invariants enforced by CHECK)
            scope_dict = c["scope"]
            session.execute(
                text(
                    "INSERT INTO memory_cards "
                    "(id, owner_id, memory_job_id, status, kind, source_type, "
                    " save_preselected, title, rule, avoid, trigger_text, "
                    " scope_level, domain, task_type, artifact_type, audience, project_key, "
                    " scope_json, exceptions_json, source_trust, evidence_count, "
                    " version, created_at, updated_at) "
                    "VALUES (:id, :owner, :job, 'candidate', :kind, 'explicit_feedback', "
                    "        :preselected, :title, :rule, :avoid, :trigger, "
                    "        :level, :domain, :task_type, :artifact, :audience, :project, "
                    "        :scope_json, :exceptions, :trust, 1, "
                    "        0, :now, :now)"
                ),
                {
                    "id": memory_id,
                    "owner": self._user_ctx.user_id,
                    "job": job.id,
                    "kind": c["kind"],
                    "preselected": c["save_preselected"],
                    "title": c["title"][:40],
                    "rule": c["rule"][:300],
                    "avoid": c["avoid"][:400],
                    "trigger": c["trigger_text"][:240],
                    "level": scope_dict.get("level", "task_family"),
                    "domain": scope_dict.get("domain", "other"),
                    "task_type": scope_dict.get("task_type"),
                    "artifact": scope_dict.get("artifact_type"),
                    "audience": scope_dict.get("audience"),
                    "project": scope_dict.get("project_key"),
                    "scope_json": json.dumps(scope_dict),
                    "exceptions": json.dumps(c["exceptions"]),
                    "trust": 1.0,
                    "now": utc_now(),
                },
            )

            # Evidence link
            link_id = new_prefixed_ulid("evlink")
            session.execute(
                text(
                    "INSERT INTO memory_evidence_links "
                    "(id, owner_id, memory_id, evidence_id, ordinal, created_at) "
                    "VALUES (:id, :owner, :mem, :ev, :ord, :now)"
                ),
                {
                    "id": link_id,
                    "owner": self._user_ctx.user_id,
                    "mem": memory_id,
                    "ev": evidence_id,
                    "ord": i,
                    "now": utc_now(),
                },
            )

            # Emit memory.candidate.created event
            try:
                ev_payload = MemoryCandidateCreatedPayload(
                    memory_job_id=job.id,
                    memory_id=memory_id,
                    evidence_id=evidence_id,
                    ordinal=i,
                )
                task_repo.append_event(
                    stream_type="task",
                    stream_id=feedback.task_id,
                    event_type=EventType.MEMORY_CANDIDATE_CREATED,
                    data=ev_payload.model_dump(mode="json"),
                )
            except Exception:
                logger.exception(
                    "Failed to emit candidate.created event for %s", memory_id
                )

            candidate_ids.append(memory_id)

        return candidate_ids


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------


def recover_stale_jobs(
    session_factory: Any,
    user_ctx: UserContext,
) -> int:
    """Mark stale running jobs from a previous process as failed.

    Called at application startup.  Any job still in ``running`` state
    after a restart is assumed to have been interrupted.
    """
    recovered = 0
    with session_scope(session_factory) as session:
        result = session.execute(
            text(
                "UPDATE memory_jobs "
                "SET status = 'failed', "
                "    stage = 'failed', "
                "    last_error_code = 'MEMORY_JOB_INTERRUPTED', "
                "    retryable = 1, "
                "    updated_at = :now "
                "WHERE owner_id = :owner "
                "  AND status = 'running' "
                "RETURNING id"
            ),
            {"owner": user_ctx.user_id, "now": utc_now()},
        ).fetchall()
        session.commit()
        recovered = len(result)
    if recovered:
        logger.info("Recovered %d stale running jobs as failed", recovered)
    return recovered
