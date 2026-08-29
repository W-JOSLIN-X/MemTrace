"""Day 6 v2.0.0: LLM Judges — Applicability and Effect.

Architecture
------------
- ApplicabilityJudge : decides whether a candidate memory is applicable,
                        overridden, conflicting, or irrelevant to current task
- EffectJudge        : decides whether a selected memory was actually applied,
                        violated, not observable, or unknown in the answer

Design rules
------------
1. Both use DeepSeek Responses API with strict json_schema output.
2. Applicability runs BEFORE injection; Effect runs AFTER answer.
3. Judge failure → "unknown"/"irrelevant", never fallback to keyword matching.
4. Server validates evidence substring; model does not decide ownership/IDs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from memtrace_api.config import Settings
from memtrace_api.providers import (
    ProviderRequest,
    ProviderUsage,
    StructuredOutput,
    StructuredProvider,
    build_structured_provider,
)
from memtrace_api.schemas import (
    ApplicabilityJudgeResult,
    EffectJudgeResult,
    utc_now,
)

logger = logging.getLogger(__name__)

_APPLICABILITY_PROMPT = """You are a memory applicability judge.

Given:
1. Current user task and explicit constraints
2. A candidate user memory (preference, rule, or experience)
3. Nearby active memories for context

Decide if this memory should be applied to the current task.

OUTPUT SCHEMA:
- result: "applicable" | "current_instruction_override" | "conflict" | "irrelevant"
- confidence: 0.0 to 1.0
- reason_code: one of [
  "semantic_match", "current_instruction_override", "memory_conflict",
  "scope_mismatch", "outdated", "irrelevant", "ambiguous"
]
- reasoning: 1-3 sentences explaining the decision

RULES:
- "applicable": memory directly relevant and no conflict with current constraints
- "current_instruction_override": current task has explicit instruction that overrides this memory
- "conflict": memory contradicts current constraints or other applicable memories
- "irrelevant": memory does not apply to this task at all
- Default to "irrelevant" when uncertain
"""


def _build_applicability_prompt(
    task_text: str,
    constraints: str,
    candidate_memory: dict[str, Any],
    nearby_memories: list[dict[str, Any]],
) -> str:
    nearby = ""
    if nearby_memories:
        parts = [
            f"- [{m.get('kind', 'unknown')}] {m.get('content', '')[:100]}\n  applies_when: {m.get('applies_when', '')[:80]}"
            for m in nearby_memories[:3]
        ]
        nearby = "\nNearby active memories:\n" + "\n".join(parts)

    return f"""## Current Task
{task_text[:2000]}

## Current Explicit Constraints
{constraints[:500] if constraints else "None"}

## Candidate Memory
Kind: {candidate_memory.get('kind', 'unknown')}
Content: {candidate_memory.get('content', '')[:1000]}
Applies when: {candidate_memory.get('applies_when', '')[:300]}

{nearby}
"""


def _build_effect_prompt(
    task_text: str,
    memory_content: str,
    answer_text: str,
) -> str:
    return f"""## Original Task
{task_text[:2000]}

## Memory That Was Injected
{memory_content[:500]}

## Agent Answer (verify if memory was applied)
{answer_text[:4000]}

Decide if the memory was actually applied in the answer.
"""


class ApplicabilityJudge:
    """LLM-driven memory applicability judge."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self._provider: StructuredProvider | None = None

    def _get_provider(self) -> StructuredProvider:
        if self._provider is None:
            self._provider = build_structured_provider(self._settings)
        return self._provider

    async def judge(
        self,
        task_text: str,
        constraints: str,
        candidate_memory: dict[str, Any],
        nearby_memories: list[dict[str, Any]] | None = None,
    ) -> ApplicabilityJudgeResult:
        """Judge if a candidate memory is applicable to current task."""
        provider = self._get_provider()
        prompt = _build_applicability_prompt(
            task_text, constraints, candidate_memory, nearby_memories or []
        )
        schema = ApplicabilityJudgeResult.model_json_schema()
        output_schema = {
            "name": "ApplicabilityJudgeResult",
            "schema": schema,
            "strict": True,
        }

        try:
            result: StructuredOutput = await provider.complete_json(
                ProviderRequest(
                    task_text=prompt,
                    output_schema=output_schema,
                )
            )
            return ApplicabilityJudgeResult.model_validate(result.parsed)
        except Exception as e:
            logger.warning("applicability_judge_failed", exc_info=e)
            return ApplicabilityJudgeResult(
                result="irrelevant",
                confidence=0.0,
                reason_code="ambiguous",
                reasoning=f"Judge failed: {e}",
            )


class EffectJudge:
    """LLM-driven memory effect judge."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self._provider: StructuredProvider | None = None

    def _get_provider(self) -> StructuredProvider:
        if self._provider is None:
            self._provider = build_structured_provider(self._settings)
        return self._provider

    async def judge(
        self,
        task_text: str,
        memory_content: str,
        answer_text: str,
    ) -> EffectJudgeResult:
        """Judge if a memory was actually applied in the answer."""
        provider = self._get_provider()
        prompt = _build_effect_prompt(task_text, memory_content, answer_text)
        schema = EffectJudgeResult.model_json_schema()
        output_schema = {
            "name": "EffectJudgeResult",
            "schema": schema,
            "strict": True,
        }

        try:
            result: StructuredOutput = await provider.complete_json(
                ProviderRequest(
                    task_text=prompt,
                    output_schema=output_schema,
                )
            )
            return EffectJudgeResult.model_validate(result.parsed)
        except Exception as e:
            logger.warning("effect_judge_failed", exc_info=e)
            # Fail-safe: return unknown
            return EffectJudgeResult(
                judgment="unknown",
                confidence=0.0,
                reason_code="judge_unavailable",
                excerpt="",
                reasoning=f"Judge failed: {e}",
            )
