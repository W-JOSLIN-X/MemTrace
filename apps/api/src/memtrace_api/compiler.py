"""Day 3 G2: Structured extraction provider and FeedbackCompiler."""

from __future__ import annotations

import json
import logging
from dataclasses import field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from memtrace_api.config import Settings
from memtrace_api.diff import compute_diff
from memtrace_api.durability import detect_durability
from memtrace_api.schemas import (
    AsyncErrorCode,
    Disposition,
    MemoryScope,
    SourceType,
    TaskFingerprint,
    utc_now,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction result schema (provider output)
# ---------------------------------------------------------------------------


class CandidateCardSchema(BaseModel):
    model_config: type[dict[str, Any]] = {"extra": "forbid"}

    category: Literal["preference", "rule", "experience", "one_shot"]  # type: ignore[name-defined]
    kind: Literal["preference", "constraint", "procedure", "experience"]  # type: ignore[name-defined]
    title: str
    rule: str
    avoid: str = ""
    trigger_text: str = ""
    scope: dict[str, Any]
    exceptions: list[str] = []
    evidence_source: Literal["explicit_text", "edit_diff"]  # type: ignore[name-defined]
    evidence_quote: str


class ExtractionSchema(BaseModel):
    model_config: type[dict[str, Any]] = {"extra": "forbid"}

    schema_version: Literal["1.0"] = "1.0"  # type: ignore[name-defined]
    feedback_summary: str
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

    @field_validator("candidates")
    @classmethod
    def at_most_three(cls, v: list[CandidateCardSchema]) -> list[CandidateCardSchema]:
        if len(v) > 3:
            raise ValueError("at most 3 candidates allowed")
        return v


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


class StructuredProvider:
    """Protocol for structured JSON extraction providers."""

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


# ---------------------------------------------------------------------------
# Failure type
# ---------------------------------------------------------------------------


class ProviderFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


# ---------------------------------------------------------------------------
# Mock structured provider
# ---------------------------------------------------------------------------


class MockStructuredProvider(StructuredProvider):
    """Deterministic structured extraction for tests and demos."""

    name = "mock-structured"
    mode = "mock"

    _RESPONSES: dict[str, dict[str, Any]] = {
        "two_candidates": {
            "schema_version": "1.0",
            "feedback_summary": "用户希望学习模式先提示再给答案，并偏好简洁中文讲解。",
            "durability": "explicit_durable",
            "disposition": "candidate_created",
            "candidates": [
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "调试学习先提示",
                    "rule": "先给一个可执行的诊断动作，再逐步增加提示。",
                    "avoid": "首次回复直接给完整修复。",
                    "trigger_text": "编程学习中的调试指导",
                    "scope": {"level": "task_family", "domain": "programming_learning"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "以后学习调试先提示",
                },
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "简洁中文讲解",
                    "rule": "使用简洁清晰的中文进行讲解。",
                    "avoid": "冗长的英文或中文解释。",
                    "trigger_text": "所有回答",
                    "scope": {"level": "task_family", "domain": "programming_learning"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "简洁清楚的讲解",
                },
            ],
        },
        "empty_json": {
            "schema_version": "1.0",
            "feedback_summary": "无有效可复用内容。",
            "durability": "ambiguous",
            "disposition": "no_memory",
            "candidates": [],
        },
        "truncated_json": {
            "schema_version": "1.0",
            "feedback_summary": "用户希望先给提示再给完整修复。",
            "durability": "explicit_durable",
            "disposition": "candidate_created",
            "candidates": [
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "学习调试先提示",
                    "rule": "先给诊断动作，再逐步增加提示。",
                    "avoid": "首次直接给完整修复。",
                    "trigger_text": "编程学习中的调试指导",
                    "scope": {"level": "task_family", "domain": "programming_learning"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "以后学习调试先提示",
                }
            ],
        },
        "unknown_fields": {
            "schema_version": "1.0",
            "feedback_summary": "用户希望先给提示再给答案。",
            "durability": "explicit_durable",
            "disposition": "candidate_created",
            "candidates": [
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "先给提示",
                    "rule": "先给提示再给完整答案。",
                    "avoid": "直接给完整答案。",
                    "trigger_text": "回答",
                    "scope": {"level": "task_family", "domain": "programming_learning"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "先给提示",
                }
            ],
            "extra_field_should_fail": "this will trigger schema rejection",
        },
        "four_candidates": {
            "schema_version": "1.0",
            "feedback_summary": "用户的多条偏好。",
            "durability": "explicit_durable",
            "disposition": "candidate_created",
            "candidates": [
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "中文讲解",
                    "rule": "使用中文。",
                    "avoid": "",
                    "trigger_text": "回答",
                    "scope": {"level": "task_family", "domain": "programming_learning"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "用中文",
                },
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "先给思路",
                    "rule": "先给思路再给结论。",
                    "avoid": "",
                    "trigger_text": "回答",
                    "scope": {"level": "task_family", "domain": "programming_learning"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "先给思路",
                },
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "附示例",
                    "rule": "附上代码示例。",
                    "avoid": "",
                    "trigger_text": "回答",
                    "scope": {"level": "task_family", "domain": "programming_learning"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "附示例",
                },
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "多余第四张",
                    "rule": "这是第四张，应该被截断。",
                    "avoid": "",
                    "trigger_text": "回答",
                    "scope": {"level": "task_family", "domain": "programming_learning"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "第四张",
                },
            ],
        },
        "evidence_not_found": {
            "schema_version": "1.0",
            "feedback_summary": "调试先提示，但证据不可定位。",
            "durability": "explicit_durable",
            "disposition": "candidate_created",
            "candidates": [
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "调试先提示",
                    "rule": "先给诊断动作，再逐步增加提示。",
                    "avoid": "首次直接给完整修复。",
                    "trigger_text": "编程学习中的调试指导",
                    "scope": {"level": "task_family", "domain": "programming_learning"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "【mock:证据不实】",
                }
            ],
        },
        "invalid_json_repair_fails": None,  # sentinel: repair also fails
    }

    async def complete_json(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        simulation: str | None = None,
    ) -> dict[str, Any]:
        if simulation == "invalid_json_repair_fails":
            raise ProviderFailure(
                "MEMORY_REPAIR_FAILED",
                "模拟：两次均返回非 JSON，repair 失败。",
                retryable=False,
            )
        if simulation and simulation in self._RESPONSES:
            result = self._RESPONSES[simulation]
            if result is None:
                raise ProviderFailure(
                    "MEMORY_REPAIR_FAILED",
                    "模拟：repair 失败。",
                    retryable=False,
                )
            return dict(result)

        return {
            "schema_version": "1.0",
            "feedback_summary": "Mock 提取结果。",
            "durability": "ambiguous",
            "disposition": "candidate_created",
            "candidates": [
                {
                    "category": "preference",
                    "kind": "preference",
                    "title": "Mock 偏好",
                    "rule": "Mock 规则正文。",
                    "avoid": "",
                    "trigger_text": "Mock",
                    "scope": {"level": "task_family", "domain": "other"},
                    "exceptions": [],
                    "evidence_source": "explicit_text",
                    "evidence_quote": "Mock",
                }
            ],
        }


# ---------------------------------------------------------------------------
# Real structured provider
# ---------------------------------------------------------------------------


class DeepSeekStructuredProvider(StructuredProvider):
    name = "deepseek-structured"
    mode = "real"

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        if settings.llm_api_key is None:
            raise ValueError("LLM_API_KEY is required")
        self.model = settings.llm_model
        self._client = client or AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            timeout=60,
            max_retries=0,
        )

    async def complete_json(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        *,
        simulation: str | None = None,
    ) -> dict[str, Any]:
        messages = [{"role": "user", "content": prompt}]
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=1024,
        )
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise ProviderFailure("MEMORY_PROVIDER_ERROR", "模型服务返回空响应。", retryable=True)
        msg = getattr(choices[0], "message", None)
        text = getattr(msg, "content", "") if msg else ""
        if not text:
            raise ProviderFailure(
                "MEMORY_JSON_INVALID",
                "模型服务返回空内容。",
                retryable=False,
            )
        return json.loads(text)


def build_structured_provider(settings: Settings) -> StructuredProvider:
    if settings.mock_mode:
        return MockStructuredProvider()
    return DeepSeekStructuredProvider(settings)
