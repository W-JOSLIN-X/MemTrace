from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from memtrace_api.judges import EffectJudge
from memtrace_api.providers import ProviderRequest, ProviderUsage, StructuredOutput
from memtrace_api.schemas import (
    ConflictConsolidationResult,
    ConsolidationDecision,
    EffectJudgment,
    EffectReasonCode,
    MemoryKindV2,
)


class UnknownSegmentProvider:
    async def complete_json(
        self,
        request: ProviderRequest,
        output_schema: dict[str, Any] | None = None,
    ) -> StructuredOutput:
        del request, output_schema
        parsed = {
            "judgment": "applied",
            "confidence": 0.99,
            "evidence_segment_id": "seg_999",
            "reason_code": "followed",
        }
        return StructuredOutput(
            raw=json.dumps(parsed),
            parsed=parsed,
            usage=ProviderUsage(
                prompt_tokens=10,
                output_tokens=5,
                total_tokens=15,
                reasoning_tokens=0,
            ),
            response_id="resp_invalid_excerpt",
            model="fixture-semantic",
            prompt_hash="sha256:" + "c" * 64,
            latency_ms=2,
        )


@pytest.mark.asyncio
async def test_effect_judge_fails_closed_when_model_segment_is_not_supplied() -> None:
    judge = EffectJudge(provider=UnknownSegmentProvider())  # type: ignore[arg-type]

    call = await judge.judge_call(
        current_turn="Explain transactions.",
        memory={
            "memory_id": "mem_01J00000000000000000000000",
            "kind": "preference",
            "content": "Lead with a conclusion.",
            "applies_when": "When explaining technical concepts.",
        },
        assistant_answer="Conclusion: transactions make grouped writes atomic.",
    )

    assert call.result.judgment is EffectJudgment.UNKNOWN
    assert call.result.reason_code is EffectReasonCode.AMBIGUOUS
    assert call.result.confidence == 0.0
    assert call.result.evidence_excerpt is None
    assert call.provider.usage.total_tokens == 15


def test_coexist_requires_an_auditable_related_memory_target() -> None:
    with pytest.raises(ValidationError, match="coexist require target_memory_id"):
        ConflictConsolidationResult(
            decision=ConsolidationDecision.COEXIST,
            target_memory_id=None,
            merged_kind=MemoryKindV2.PREFERENCE,
            merged_content="Use detailed explanations for product copy.",
            merged_applies_when="When writing product-facing copy.",
            reason_code="related_distinct_scope",
            confidence=0.96,
        )

    accepted = ConflictConsolidationResult(
        decision=ConsolidationDecision.COEXIST,
        target_memory_id="mem_01J00000000000000000000000",
        merged_kind=MemoryKindV2.PREFERENCE,
        merged_content="Use detailed explanations for product copy.",
        merged_applies_when="When writing product-facing copy.",
        reason_code="related_distinct_scope",
        confidence=0.96,
    )
    assert accepted.target_memory_id == "mem_01J00000000000000000000000"
