"""Structured candidate extraction for the Day 3 feedback compiler."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from memtrace_api.config import Settings
from memtrace_api.providers import (
    DeepSeekProvider as ResponsesDeepSeekProvider,
)
from memtrace_api.providers import (
    ProviderFailure as ResponsesProviderFailure,
)
from memtrace_api.providers import (
    ProviderRequest as ResponsesProviderRequest,
)
from memtrace_api.providers import (
    StructuredProvider as ResponsesStructuredProvider,
)
from memtrace_api.schemas import AllowedException, AsyncErrorCode, MemoryScope

logger = logging.getLogger(__name__)


class CandidateCardSchema(BaseModel):
    """Strict provider output; owner, status, trust, and version are server-derived."""

    model_config = ConfigDict(extra="forbid")

    category: Literal["preference", "rule", "experience", "one_shot"]
    kind: Literal["preference", "constraint", "procedure", "experience"]
    title: Annotated[str, StringConstraints(min_length=4, max_length=40)]
    rule: Annotated[str, StringConstraints(min_length=20, max_length=300)]
    avoid: Annotated[str, StringConstraints(max_length=400)] = ""
    trigger_text: Annotated[str, StringConstraints(max_length=240)] = ""
    scope: MemoryScope
    exceptions: list[AllowedException] = Field(default_factory=list, max_length=8)
    evidence_source: Literal["explicit_text", "edit_diff"]
    evidence_quote: Annotated[str, StringConstraints(min_length=1, max_length=2_000)]


class ExtractionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    feedback_summary: Annotated[str, StringConstraints(min_length=1, max_length=1_000)]
    durability: Literal[
        "explicit_durable",
        "one_shot",
        "ambiguous",
        "reinforce_usage_only",
        "harmful_usage_only",
    ]
    disposition: Literal[
        "candidate_created",
        "episode_only",
        "reinforce_usage_only",
        "no_memory",
        "failed",
    ]
    candidates: list[CandidateCardSchema] = Field(default_factory=list, max_length=3)


class StructuredProvider:
    """Small async protocol shared by the deterministic and real providers."""

    name: str
    mode: str

    async def complete_json(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        simulation: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class ProviderFailure(Exception):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _valid_candidate(
    *,
    evidence_quote: str,
    evidence_source: Literal["explicit_text", "edit_diff"] = "explicit_text",
    title: str = "后续回答表达偏好",
    kind: Literal["preference", "constraint", "procedure", "experience"] = "preference",
) -> dict[str, Any]:
    return {
        "category": (
            "preference"
            if kind == "preference"
            else "experience"
            if kind == "experience"
            else "rule"
        ),
        "kind": kind,
        "title": title,
        "rule": "在后续相似任务中，应持续遵循这条由用户反馈明确表达的要求。",
        "avoid": "",
        "trigger_text": "与当前任务类型相同的后续任务",
        "scope": {"level": "session", "domain": "other"},
        "exceptions": [],
        "evidence_source": evidence_source,
        "evidence_quote": evidence_quote,
    }


class MockStructuredProvider(StructuredProvider):
    """Deterministic extraction used by the demo, automated tests, and Docker gate."""

    name = "mock-structured"
    mode = "mock"

    async def complete_json(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        simulation: str | None = None,
    ) -> dict[str, Any]:
        del output_schema
        context = _context_from_prompt(prompt)
        explicit_simulation = simulation is not None
        if simulation is None:
            simulation = _mock_simulation(context)
        repairing = "previous_output" in context
        if simulation in {"provider_failure", "provider_timeout"}:
            code = (
                "MEMORY_PROVIDER_TIMEOUT"
                if simulation == "provider_timeout"
                else "MEMORY_PROVIDER_ERROR"
            )
            raise ProviderFailure(code, retryable=True)
        if simulation == "invalid_json_repair_fails":
            raise ProviderFailure("MEMORY_REPAIR_FAILED", retryable=False)
        if simulation == "empty_json":
            if repairing or explicit_simulation:
                return self._empty("ambiguous")
            return {}
        if repairing and simulation in {
            "truncated_json",
            "unknown_fields",
            "four_candidates",
        }:
            return self._repaired(context, simulation)
        if simulation == "truncated_json":
            return {"schema_version": "1.0"}
        if simulation == "two_candidates":
            return self._scripted_candidates(context, count=2)
        if simulation == "four_candidates":
            return self._scripted_candidates(context, count=4)
        if simulation == "evidence_not_found":
            body = self._empty("explicit_durable")
            body["disposition"] = "candidate_created"
            body["candidates"] = [_valid_candidate(evidence_quote="不存在的模拟证据")]
            return body
        if simulation == "unknown_fields":
            invalid = self._scripted_candidates(context, count=1)
            invalid["unknown"] = True
            return invalid

        explicit_text = _optional_text(context.get("explicit_text"))
        edited_output = _optional_text(context.get("edited_output"))
        durability = str(context.get("durability") or "ambiguous")
        if explicit_text is not None:
            source: Literal["explicit_text", "edit_diff"] = "explicit_text"
            quote = explicit_text[:2_000]
        elif edited_output is not None:
            source = "edit_diff"
            quote = edited_output[:2_000]
        else:
            return self._empty("ambiguous")
        if source == "edit_diff" and _looks_like_factual_correction(quote):
            return self._empty(durability)

        kind = _infer_kind(quote)
        title = {
            "preference": "后续回答表达偏好",
            "constraint": "后续回答约束要求",
            "procedure": "后续任务执行步骤",
            "experience": "后续任务有效经验",
        }[kind]
        candidate = _valid_candidate(
            evidence_quote=quote,
            evidence_source=source,
            title=title,
            kind=kind,
        )
        candidate["rule"] = _rule_from_feedback(quote)
        return {
            "schema_version": "1.0",
            "feedback_summary": "检测到一条可进入准入流程的用户反馈信号。",
            "durability": durability,
            "disposition": "candidate_created",
            "candidates": [candidate],
        }

    def _scripted_candidates(
        self,
        context: dict[str, Any],
        *,
        count: int,
    ) -> dict[str, Any]:
        quote = _simulation_evidence(context)
        candidate = _valid_candidate(evidence_quote=quote)
        candidate["rule"] = _rule_from_feedback(quote)
        body = self._empty("explicit_durable")
        body["disposition"] = "candidate_created"
        body["candidates"] = [dict(candidate) for _ in range(count)]
        return body

    def _repaired(self, context: dict[str, Any], simulation: str) -> dict[str, Any]:
        if simulation == "four_candidates":
            return self._scripted_candidates(context, count=3)
        return self._scripted_candidates(context, count=1)

    @staticmethod
    def _empty(durability: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "feedback_summary": "未检测到可复用的候选内容。",
            "durability": durability,
            "disposition": "no_memory",
            "candidates": [],
        }


class DeepSeekStructuredProvider(StructuredProvider):
    """Legacy G2 adapter over the same strict Responses provider used by G5."""

    name = "deepseek-structured"
    mode = "real"

    def __init__(
        self,
        settings: Settings,
        *,
        provider: ResponsesStructuredProvider | None = None,
    ) -> None:
        self.model = settings.llm_model
        self._provider = provider or ResponsesDeepSeekProvider(settings)

    async def complete_json(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        simulation: str | None = None,
    ) -> dict[str, Any]:
        del simulation
        schema = {
            "name": "legacy_memory_extraction",
            "schema": output_schema,
            "strict": True,
        }
        schema_failure_kinds = {
            "structured_json_invalid",
            "structured_not_object",
            "structured_schema_invalid",
        }
        current_prompt = prompt
        for schema_attempt in range(2):
            try:
                output = await self._provider.complete_json(
                    ResponsesProviderRequest(
                        task_text=current_prompt,
                        output_schema=schema,
                        stage="reflection",
                    ),
                    schema,
                )
            except ResponsesProviderFailure as exc:
                logger.warning(
                    "legacy_memory_provider.failed stage=reflection code=%s status=%s "
                    "failure_kind=%s retryable=%s detail=%s schema_attempt=%s",
                    exc.code.value,
                    exc.provider_status,
                    exc.failure_kind,
                    exc.retryable,
                    exc.message,
                    schema_attempt + 1,
                )
                if exc.failure_kind in schema_failure_kinds and schema_attempt == 0:
                    current_prompt = (
                        prompt
                        + "\n\nSCHEMA_REPAIR_REQUIRED\n"
                        + "The prior generated object was rejected by strict server-side "
                        + "JSON Schema validation. Generate the object again from the "
                        + "original evidence without adding or changing its meaning. "
                        + "Obey every required field, enum, array bound, and string "
                        + "minLength/maxLength exactly; keep titles concise (at most 40 "
                        + "Unicode characters). Do not include markdown or unknown fields.\n"
                        + f"CONTROLLED_VALIDATION_DETAIL: {exc.message}"
                    )
                    continue
                if exc.failure_kind in schema_failure_kinds:
                    raise ProviderFailure("MEMORY_REPAIR_FAILED", retryable=False) from exc
                code = (
                    "MEMORY_PROVIDER_TIMEOUT"
                    if exc.code is AsyncErrorCode.PROVIDER_TIMEOUT
                    else "MEMORY_PROVIDER_ERROR"
                )
                raise ProviderFailure(code, retryable=exc.retryable) from exc
            return output.parsed
        raise RuntimeError("unreachable schema repair state")  # pragma: no cover

    async def aclose(self) -> None:
        await self._provider.aclose()


def _context_from_prompt(prompt: str) -> dict[str, Any]:
    marker = "MEMTRACE_CONTEXT_JSON:"
    for line in prompt.splitlines():
        if line.startswith(marker):
            try:
                value = json.loads(line[len(marker) :])
            except json.JSONDecodeError:
                return {}
            return value if isinstance(value, dict) else {}
    return {}


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _infer_kind(text: str) -> Literal["preference", "constraint", "procedure", "experience"]:
    folded = text.casefold()
    if any(cue in folded for cue in ("不要", "禁止", "必须", "must", "never", "always")):
        return "constraint"
    if any(cue in folded for cue in ("我发现", "我的经验", "worked", "works", "有效", "可行")):
        return "experience"
    if any(cue in folded for cue in ("先", "然后", "步骤", "first", "then")):
        return "procedure"
    if "经验" in folded:
        return "experience"
    return "preference"


def _mock_simulation(context: dict[str, Any]) -> str | None:
    text = " ".join(
        value
        for value in (context.get("explicit_text"), context.get("edited_output"))
        if isinstance(value, str)
    )
    markers = {
        "【mock:证据不实】": "evidence_not_found",
        "【mock:四张候选】": "four_candidates",
        "【mock:修复失败】": "invalid_json_repair_fails",
        "【mock:空JSON】": "empty_json",
        "【mock:截断JSON】": "truncated_json",
        "【mock:未知字段】": "unknown_fields",
        "【mock:两张候选】": "two_candidates",
    }
    return next((simulation for marker, simulation in markers.items() if marker in text), None)


def _simulation_evidence(context: dict[str, Any]) -> str:
    quote = _optional_text(context.get("explicit_text")) or _optional_text(
        context.get("edited_output")
    )
    return (quote or "受控 Mock 候选证据")[:2_000]


def _looks_like_factual_correction(text: str) -> bool:
    folded = text.casefold()
    return any(cue in folded for cue in ("实际问题是", "事实是", "actually", "the issue is"))


def _rule_from_feedback(text: str) -> str:
    compact = " ".join(text.split())[:240]
    rule = f"在后续相似任务中，应遵循用户明确反馈的要求：{compact}"
    if len(rule) < 20:
        rule += "，并在输出前检查是否满足该要求。"
    return rule[:300]


def build_structured_provider(settings: Settings) -> StructuredProvider:
    if settings.mock_mode:
        return MockStructuredProvider()
    return DeepSeekStructuredProvider(settings)
