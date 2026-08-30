"""Real-provider checkpoint A for all G5 semantic components.

Only controlled enums and provider metadata are emitted. Synthetic prompts and
model text remain in memory and are never printed or persisted.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_SRC = PROJECT_ROOT / "apps" / "api" / "src"
sys.path.insert(0, str(API_SRC))

from memtrace_api.config import Settings
from memtrace_api.judges import (
    ApplicabilityJudge,
    ConsolidationJudge,
    EffectJudge,
)
from memtrace_api.memory_worker import (
    MemoryManager,
    ReflectionContext,
)
from memtrace_api.providers import (
    DeepSeekProvider,
    ProviderFailure,
    ProviderMessage,
    ProviderRequest,
)
from memtrace_api.schemas import ProviderMode


def _usage_record(stage: str, output: object) -> dict[str, object]:
    usage = output.usage
    return {
        "stage": stage,
        "model": output.model,
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "latency_ms": output.latency_ms,
        "prompt_hash_present": output.prompt_hash.startswith("sha256:"),
    }


async def _run() -> int:
    settings = Settings()
    report: dict[str, object] = {
        "has_llm_api_key": settings.has_llm_api_key,
        "provider_mode": settings.provider_mode,
        "configured_model": settings.llm_model,
        "stages": [],
    }
    if settings.mock_mode or not settings.has_llm_api_key:
        report["error_code"] = "REAL_PROVIDER_NOT_CONFIGURED"
        print(json.dumps(report, separators=(",", ":")))
        return 2
    provider = DeepSeekProvider(settings)
    if provider.mode is not ProviderMode.REAL:
        report["error_code"] = "MOCK_FALLBACK"
        print(json.dumps(report, separators=(",", ":")))
        return 3
    stages: list[dict[str, object]] = []
    try:
        final = None
        answer_parts: list[str] = []
        async for item in provider.stream(
            ProviderRequest(
                task_text="请解释什么是闭包。",
                conversation=(
                    ProviderMessage(role="user", content="请解释什么是闭包。"),
                ),
                stage="chat",
            )
        ):
            if item.delta:
                answer_parts.append(item.delta)
            if item.finish_reason is not None:
                final = item
        if final is None or final.usage is None or not "".join(answer_parts):
            raise RuntimeError("chat_missing_output_or_usage")
        stages.append(
            {
                "stage": "chat",
                "model": final.model,
                "input_tokens": final.usage.prompt_tokens,
                "output_tokens": final.usage.output_tokens,
                "total_tokens": final.usage.total_tokens,
                "latency_ms": final.latency_ms,
                "prompt_hash_present": bool(
                    final.prompt_hash and final.prompt_hash.startswith("sha256:")
                ),
            }
        )

        manager = MemoryManager(settings, provider=provider)
        extraction = await manager.extract(
            ReflectionContext(
                job_id="job_01J00000000000000000000000",
                owner_id="usr_01J00000000000000000000000",
                task_id="task_01J00000000000000000000000",
                run_id="run_01J00000000000000000000000",
                turn_index=1,
                user_message_id="msg_01J00000000000000000000000",
                user_message="以后回答技术问题时，请先给结论，再解释依据。",
                assistant_message_id="msg_01J00000000000000000000001",
                assistant_message="明白。",
                active_memories=(),
            )
        )
        stages.append(
            {
                **_usage_record("reflection", extraction.provider),
                "decision": extraction.batch.decision.value,
                "operation_count": len(extraction.batch.operations),
                "kinds": sorted(
                    {item.kind.value for item in extraction.batch.operations}
                ),
            }
        )
        if not extraction.batch.operations:
            raise RuntimeError("reflection_returned_no_operation")
        candidate = extraction.batch.operations[0]

        consolidation = await ConsolidationJudge(provider=provider).judge_call(
            candidate=candidate,
            active_memories=[],
        )
        stages.append(
            {
                **_usage_record("consolidation", consolidation.provider),
                "decision": consolidation.result.decision.value,
            }
        )
        memory = {
            "memory_id": "mem_01J00000000000000000000000",
            "kind": candidate.kind.value,
            "content": candidate.content,
            "applies_when": candidate.applies_when,
            "current_version_id": "memver_01J00000000000000000000000",
        }
        applicability = await ApplicabilityJudge(provider=provider).judge_call(
            current_turn="请用另一种说法解释 Python 闭包。",
            candidate_memory=memory,
            active_memories=[],
        )
        stages.append(
            {
                **_usage_record("applicability", applicability.provider),
                "result": applicability.result.applicability.value,
                "reason_code": applicability.result.reason_code.value,
            }
        )
        answer = "结论：闭包是保存了外层作用域变量的函数。随后说明其形成条件。"
        effect = await EffectJudge(provider=provider).judge_call(
            current_turn="请解释 Python 闭包。",
            memory=memory,
            assistant_answer=answer,
        )
        stages.append(
            {
                **_usage_record("effect", effect.provider),
                "result": effect.result.judgment.value,
                "reason_code": effect.result.reason_code.value,
                "evidence_exact": (
                    effect.result.evidence_excerpt is None
                    or effect.result.evidence_excerpt in answer
                ),
            }
        )

        scoped_user_message = (
            "另一个长期偏好：当我让我设计 NoSQL 文档数据库索引时，不要列风险，"
            "先给一个示例查询；它只适用于 NoSQL，与关系型数据库偏好并存。"
        )
        scoped_extraction = await manager.extract(
            ReflectionContext(
                job_id="job_01J00000000000000000000002",
                owner_id="usr_01J00000000000000000000000",
                task_id="task_01J00000000000000000000002",
                run_id="run_01J00000000000000000000002",
                turn_index=1,
                user_message_id="msg_01J00000000000000000000002",
                user_message=scoped_user_message,
                assistant_message_id="msg_01J00000000000000000000003",
                assistant_message="明白。",
                active_memories=(),
            )
        )
        scoped_operations = scoped_extraction.batch.operations
        scoped_candidate = scoped_operations[0] if len(scoped_operations) == 1 else None
        scoped_text = (
            f"{scoped_candidate.content}\n{scoped_candidate.applies_when}"
            if scoped_candidate is not None
            else ""
        )
        scoped_isolated = (
            scoped_candidate is not None
            and "NoSQL" in scoped_text
            and "关系型" not in scoped_text
        )
        stages.append(
            {
                **_usage_record(
                    "reflection_scope_isolation", scoped_extraction.provider
                ),
                "operation_count": len(scoped_operations),
                "scope_isolated": scoped_isolated,
            }
        )
        if scoped_candidate is None or not scoped_isolated:
            raise RuntimeError("reflection_scope_isolation_failed")

        relational_memory = {
            "memory_id": "mem_01J00000000000000000000002",
            "kind": "preference",
            "content": "设计关系型数据库索引时，只列出一个首要风险，再给建议。",
            "applies_when": "设计关系型数据库索引并提供建议时",
            "current_version_id": "memver_01J00000000000000000000002",
        }
        scoped_consolidation = await ConsolidationJudge(provider=provider).judge_call(
            candidate=scoped_candidate,
            active_memories=[relational_memory],
        )
        stages.append(
            {
                **_usage_record(
                    "consolidation_scope_isolation", scoped_consolidation.provider
                ),
                "decision": scoped_consolidation.result.decision.value,
            }
        )
        if scoped_consolidation.result.decision.value != "coexist":
            raise RuntimeError("scoped_consolidation_did_not_coexist")

        scoped_memory = {
            "memory_id": "mem_01J00000000000000000000003",
            "kind": scoped_candidate.kind.value,
            "content": scoped_candidate.content,
            "applies_when": scoped_candidate.applies_when,
            "current_version_id": "memver_01J00000000000000000000003",
        }
        scoped_turn = "请为 MongoDB 订单集合设计 customerId 和 status 的索引。"
        relational_applicability = await ApplicabilityJudge(
            provider=provider
        ).judge_call(
            current_turn=scoped_turn,
            candidate_memory=relational_memory,
            active_memories=[scoped_memory],
        )
        scoped_applicability = await ApplicabilityJudge(provider=provider).judge_call(
            current_turn=scoped_turn,
            candidate_memory=scoped_memory,
            active_memories=[relational_memory],
        )
        stages.extend(
            [
                {
                    **_usage_record(
                        "applicability_scope_mismatch",
                        relational_applicability.provider,
                    ),
                    "result": relational_applicability.result.applicability.value,
                },
                {
                    **_usage_record(
                        "applicability_scope_match",
                        scoped_applicability.provider,
                    ),
                    "result": scoped_applicability.result.applicability.value,
                },
            ]
        )
        if relational_applicability.result.applicability.value != "irrelevant":
            raise RuntimeError("scoped_relational_memory_misactivated")
        if scoped_applicability.result.applicability.value != "applicable":
            raise RuntimeError("scoped_nosql_memory_not_applicable")
    except ProviderFailure as exc:
        report["error_code"] = exc.code.value
        report["retryable"] = exc.retryable
        report["provider_status"] = exc.provider_status
        report["completed_stages"] = stages
        print(json.dumps(report, separators=(",", ":"), ensure_ascii=True))
        await provider.aclose()
        return 4
    except (RuntimeError, ValueError, TypeError) as exc:
        report["error_code"] = type(exc).__name__
        report["completed_stages"] = stages
        print(json.dumps(report, separators=(",", ":"), ensure_ascii=True))
        await provider.aclose()
        return 5
    await provider.aclose()
    if any(
        item.get("model") != settings.llm_model
        or not isinstance(item.get("total_tokens"), int)
        or item.get("total_tokens", 0) <= 0
        for item in stages
    ):
        report["error_code"] = "MISSING_ACTUAL_USAGE_OR_MODEL_MISMATCH"
        report["completed_stages"] = stages
        print(json.dumps(report, separators=(",", ":"), ensure_ascii=True))
        return 6
    report["stages"] = stages
    report["status"] = "ok"
    print(json.dumps(report, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
