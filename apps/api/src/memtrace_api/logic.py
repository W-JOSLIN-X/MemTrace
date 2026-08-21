"""Deterministic fingerprint, tool-decision, and public-plan logic."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.schemas import (
    ArtifactType,
    Audience,
    Domain,
    ProgrammingLanguage,
    PublicPlan,
    TaskCreateRequest,
    TaskFingerprint,
    TaskType,
    ToolAction,
    ToolDecision,
    ToolReasonCode,
)
from memtrace_api.tools import ExtractedPython, extract_python


@dataclass(frozen=True, slots=True)
class TaskAnalysis:
    fingerprint: TaskFingerprint
    tool_decision: ToolDecision
    extracted_python: ExtractedPython | None
    goal_code: Literal["analyze_code", "answer_question", "explain_concept", "other"]
    next_action_code: Literal["python_ast_check", "generate_directly"]


_LANGUAGE_FENCES = (
    (re.compile(r"```(?:python|py)\b", re.IGNORECASE), ProgrammingLanguage.PYTHON),
    (re.compile(r"```(?:javascript|js)\b", re.IGNORECASE), ProgrammingLanguage.JAVASCRIPT),
    (re.compile(r"```(?:typescript|ts)\b", re.IGNORECASE), ProgrammingLanguage.TYPESCRIPT),
    (re.compile(r"```java\b", re.IGNORECASE), ProgrammingLanguage.JAVA),
    (re.compile(r"```c\b", re.IGNORECASE), ProgrammingLanguage.C),
    (re.compile(r"```(?:cpp|c\+\+)\b", re.IGNORECASE), ProgrammingLanguage.CPP),
    (re.compile(r"```rust\b", re.IGNORECASE), ProgrammingLanguage.RUST),
    (re.compile(r"```go\b", re.IGNORECASE), ProgrammingLanguage.GO),
)

_CONCEPT_KEYWORDS = {
    "syntax": ("syntax", "语法"),
    "exception": ("exception", "traceback", "异常", "报错"),
    "loop": ("loop", "for ", "while ", "循环"),
    "function": ("def ", "function", "函数"),
    "testing": ("pytest", "unit test", "测试"),
    "api": ("api", "接口"),
    "configuration": ("config", "environment", "环境", "配置"),
    "debugging": ("debug", "bug", "修复", "调试"),
}


def _detect_language(text: str, extracted: ExtractedPython | None) -> ProgrammingLanguage:
    if extracted is not None:
        return ProgrammingLanguage.PYTHON
    for pattern, language in _LANGUAGE_FENCES:
        if pattern.search(text):
            return language
    lowered = text.lower()
    if any(token in lowered for token in ("python", "pytest", "traceback", "pip ")):
        return ProgrammingLanguage.PYTHON
    if "typescript" in lowered:
        return ProgrammingLanguage.TYPESCRIPT
    if any(token in lowered for token in ("javascript", "node.js", "npm ")):
        return ProgrammingLanguage.JAVASCRIPT
    return ProgrammingLanguage.UNKNOWN


def _detect_task_type(text: str) -> TaskType:
    lowered = text.lower()
    if any(token in lowered for token in ("bug", "debug", "报错", "错误", "修复", "traceback")):
        return TaskType.DEBUGGING_GUIDANCE
    if any(token in lowered for token in ("review", "审查", "检查代码")):
        return TaskType.CODE_REVIEW
    if any(token in lowered for token in ("解释", "explain", "为什么", "原理")):
        return TaskType.CODE_EXPLANATION
    if any(token in lowered for token in ("生成代码", "write code", "implement", "实现")):
        return TaskType.CODE_GENERATION
    if any(token in lowered for token in ("环境", "配置", "install", "setup")):
        return TaskType.ENVIRONMENT_CONFIGURATION
    return TaskType.GENERAL_QUESTION


def _detect_framework(text: str) -> str | None:
    lowered = text.lower()
    for framework in ("fastapi", "django", "flask", "react", "vue", "spring", "pytest"):
        if framework in lowered:
            return framework
    return None


def _detect_concepts(text: str) -> list[str]:
    lowered = text.lower()
    return [
        concept
        for concept, keywords in _CONCEPT_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ][:12]


def _tool_decision(
    language: ProgrammingLanguage, extracted: ExtractedPython | None
) -> ToolDecision:
    if extracted is not None:
        return ToolDecision(
            action=ToolAction.CALL,
            tool_name="python_ast_check",
            reason_code=ToolReasonCode.PYTHON_CODE_DETECTED,
            reason="检测到可安全静态解析的 Python 代码，先进行语法结构检查。",
        )
    if language is ProgrammingLanguage.PYTHON:
        return ToolDecision(
            action=ToolAction.SKIP,
            tool_name=None,
            reason_code=ToolReasonCode.NO_EXTRACTABLE_PYTHON,
            reason="任务涉及 Python，但没有可按 G0 规则提取的代码块。",
        )
    if language is not ProgrammingLanguage.UNKNOWN:
        return ToolDecision(
            action=ToolAction.SKIP,
            tool_name=None,
            reason_code=ToolReasonCode.NON_PYTHON_TASK,
            reason="当前代码不是 Python，Day 1 的 Python AST 工具不适用。",
        )
    return ToolDecision(
        action=ToolAction.SKIP,
        tool_name=None,
        reason_code=ToolReasonCode.NON_PYTHON_TASK,
        reason="当前任务没有可解析的 Python 代码，Day 1 静态工具不适用。",
    )


def analyze_task(request: TaskCreateRequest) -> TaskAnalysis:
    text = request.task_text
    extracted = extract_python(text)
    language = _detect_language(text, extracted)
    task_type = _detect_task_type(text)
    decision = _tool_decision(language, extracted)
    concepts = _detect_concepts(text)
    has_code = language is not ProgrammingLanguage.UNKNOWN or "```" in text

    domain = Domain(request.scenario.value)
    artifact_type = ArtifactType.SOURCE_CODE if has_code else ArtifactType.NONE
    audience = (
        Audience.BEGINNER
        if any(token in text.lower() for token in ("初学", "新手", "beginner", "入门"))
        else Audience.UNKNOWN
    )
    semantic_parts = [
        f"domain:{domain.value}",
        f"task_type:{task_type.value}",
        f"language:{language.value}",
    ]
    semantic_parts.extend(f"concept:{concept}" for concept in concepts)
    fingerprint = TaskFingerprint(
        id=new_prefixed_ulid("fp"),
        domain=domain,
        task_type=task_type,
        artifact_type=artifact_type,
        audience=audience,
        project_key=None,
        language=language,
        framework=_detect_framework(text),
        concepts=concepts,
        tool_context=["python_ast_check"] if decision.action is ToolAction.CALL else [],
        current_constraints=request.current_constraints,
        semantic_query=" ".join(semantic_parts),
    )
    if task_type in {TaskType.CODE_EXPLANATION, TaskType.GENERAL_QUESTION}:
        goal_code: Literal["analyze_code", "answer_question", "explain_concept", "other"] = (
            "explain_concept" if task_type is TaskType.CODE_EXPLANATION else "answer_question"
        )
    elif has_code:
        goal_code = "analyze_code"
    else:
        goal_code = "other"
    return TaskAnalysis(
        fingerprint=fingerprint,
        tool_decision=decision,
        extracted_python=extracted,
        goal_code=goal_code,
        next_action_code=(
            "python_ast_check" if decision.action is ToolAction.CALL else "generate_directly"
        ),
    )


def build_public_plan(analysis: TaskAnalysis) -> PublicPlan:
    goals = {
        "analyze_code": "分析任务中的代码与问题，并给出可执行的下一步建议。",
        "answer_question": "直接回答当前问题，并说明关键依据。",
        "explain_concept": "解释相关编程概念，并结合当前任务给出建议。",
        "other": "理解当前任务并生成清晰、可执行的回答。",
    }
    next_action = (
        "先运行只读 Python AST 语法检查，再结合结果生成回答。"
        if analysis.next_action_code == "python_ast_check"
        else "当前没有适用的白名单静态工具，将直接生成回答。"
    )
    return PublicPlan(
        id=new_prefixed_ulid("plan"),
        goal=goals[analysis.goal_code],
        memory_summary="Day 1 尚无长期记忆，本次不会注入历史偏好。",
        next_action=next_action,
    )
