"""Frozen G1 compatibility classification and static-tool decision logic.

This module serves only the versioned /api/v1 contract. The G5 conversation
path does not use these keyword-derived fields for any memory decision.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.schemas import (
    ArtifactType,
    Audience,
    ClassificationReasonCode,
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


_FENCE = chr(96) * 3
_LANGUAGE_FENCES = (
    (re.compile(re.escape(_FENCE) + r"(?:python|py)\b", re.IGNORECASE), ProgrammingLanguage.PYTHON),
    (
        re.compile(re.escape(_FENCE) + r"(?:javascript|js)\b", re.IGNORECASE),
        ProgrammingLanguage.JAVASCRIPT,
    ),
    (
        re.compile(re.escape(_FENCE) + r"(?:typescript|ts)\b", re.IGNORECASE),
        ProgrammingLanguage.TYPESCRIPT,
    ),
    (re.compile(re.escape(_FENCE) + r"java\b", re.IGNORECASE), ProgrammingLanguage.JAVA),
    (re.compile(re.escape(_FENCE) + r"c\b", re.IGNORECASE), ProgrammingLanguage.C),
    (
        re.compile(re.escape(_FENCE) + r"(?:cpp|c\+\+)\b", re.IGNORECASE),
        ProgrammingLanguage.CPP,
    ),
    (re.compile(re.escape(_FENCE) + r"rust\b", re.IGNORECASE), ProgrammingLanguage.RUST),
    (re.compile(re.escape(_FENCE) + r"go\b", re.IGNORECASE), ProgrammingLanguage.GO),
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
    "recursion": ("recursion", "recursive", "递归"),
}
_DEBUGGING_CUES = ("traceback", "exception", "报错", "错误", "调试", "debug", "bug")
_LEARNING_CUES = (
    "学习",
    "教程",
    "初学者",
    "初学",
    "新手",
    "入门",
    "提示而不是答案",
    "不要直接给答案",
    "teach me",
    "tutorial",
    "beginner",
    "hint not the answer",
    "guide me",
)
_EXPLANATION_CUES = (
    "解释",
    "说明",
    "为什么",
    "原理",
    "讲解",
    "explain",
    "why",
    "walk me through",
)
_DEVELOPMENT_CUES = (
    "实现",
    "重构",
    "审查",
    "代码审查",
    "修复",
    "开发",
    "feature",
    "implement",
    "refactor",
    "review",
    "fix",
    "production code",
)
_DEPLOYMENT_CUES = (
    "部署",
    "环境配置",
    "依赖",
    "上线",
    "devops",
    "deploy",
    "deployment",
    "environment setup",
    "configure",
    "configuration",
    "dependency",
    "dependencies",
    "install",
    "setup",
)
_TEXT_TASK_CUES = (
    "改写",
    "总结",
    "翻译",
    "语气",
    "格式",
    "润色",
    "rewrite",
    "summarize",
    "summary",
    "translate",
    "tone",
    "format",
    "proofread",
)


def _normalize_for_rules(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _contains_cue(text: str, cues: tuple[str, ...]) -> bool:
    for cue in cues:
        if cue.isascii() and cue.replace(" ", "").isalnum():
            if re.search(rf"(?<![\w]){re.escape(cue)}(?![\w])", text):
                return True
        elif cue in text:
            return True
    return False


def _classify_domain(
    *,
    text: str,
    extracted: ExtractedPython | None,
    language: ProgrammingLanguage,
    framework: str | None,
    concepts: list[str],
) -> tuple[Domain, float, list[ClassificationReasonCode]]:
    normalized = _normalize_for_rules(text)
    code_present = extracted is not None or _FENCE in normalized
    technical_context = not code_present and (
        language is not ProgrammingLanguage.UNKNOWN or framework is not None or bool(concepts)
    )
    debugging_cue = _contains_cue(normalized, _DEBUGGING_CUES)
    learning_cue = _contains_cue(normalized, _LEARNING_CUES)
    explanation_intent = _contains_cue(normalized, _EXPLANATION_CUES) and (
        code_present or technical_context or debugging_cue
    )
    development_action = _contains_cue(normalized, _DEVELOPMENT_CUES)
    deployment_cue = _contains_cue(normalized, _DEPLOYMENT_CUES)
    text_task = _contains_cue(normalized, _TEXT_TASK_CUES) and not (
        code_present or technical_context or debugging_cue or development_action or deployment_cue
    )
    signals = (
        (ClassificationReasonCode.CODE_PRESENT, code_present),
        (ClassificationReasonCode.TECHNICAL_CONTEXT, technical_context),
        (ClassificationReasonCode.DEBUGGING_CUE, debugging_cue),
        (ClassificationReasonCode.LEARNING_CUE, learning_cue),
        (ClassificationReasonCode.EXPLANATION_INTENT, explanation_intent),
        (ClassificationReasonCode.DEVELOPMENT_ACTION, development_action),
        (ClassificationReasonCode.DEPLOYMENT_CUE, deployment_cue),
        (ClassificationReasonCode.TEXT_TASK, text_task),
    )
    detected = [reason for reason, present in signals if present]
    scores = {
        Domain.PROGRAMMING_LEARNING: (
            int(code_present)
            + int(technical_context)
            + 3 * int(debugging_cue)
            + 3 * int(learning_cue)
            + 2 * int(explanation_intent)
        ),
        Domain.SOFTWARE_DEVELOPMENT: (
            int(code_present)
            + int(technical_context)
            + 3 * int(development_action)
            + 3 * int(deployment_cue)
        ),
        Domain.GENERAL_TEXT: 4 * int(text_task),
    }
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
    (top_domain, top_score), (_, second_score) = ranked[:2]
    if top_score < 3 or top_score == second_score:
        confidence = 0.2 if top_score == 0 else 0.3
        return (
            Domain.OTHER,
            confidence,
            [
                *detected[:4],
                ClassificationReasonCode.AMBIGUOUS,
            ],
        )
    confidence = round(
        min(
            0.95,
            0.50 + 0.06 * min(top_score, 5) + 0.05 * min(top_score - second_score, 3),
        ),
        2,
    )
    allowed = {
        Domain.PROGRAMMING_LEARNING: {
            ClassificationReasonCode.CODE_PRESENT,
            ClassificationReasonCode.TECHNICAL_CONTEXT,
            ClassificationReasonCode.DEBUGGING_CUE,
            ClassificationReasonCode.LEARNING_CUE,
            ClassificationReasonCode.EXPLANATION_INTENT,
        },
        Domain.SOFTWARE_DEVELOPMENT: {
            ClassificationReasonCode.CODE_PRESENT,
            ClassificationReasonCode.TECHNICAL_CONTEXT,
            ClassificationReasonCode.DEVELOPMENT_ACTION,
            ClassificationReasonCode.DEPLOYMENT_CUE,
        },
        Domain.GENERAL_TEXT: {ClassificationReasonCode.TEXT_TASK},
    }
    return (
        top_domain,
        confidence,
        [reason for reason in detected if reason in allowed[top_domain]][:5],
    )


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
    if any(token in lowered for token in ("解释", "说明", "explain", "为什么", "原理")):
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
            reason="任务涉及 Python，但没有可按 G1 规则提取的代码块。",
        )
    return ToolDecision(
        action=ToolAction.SKIP,
        tool_name=None,
        reason_code=ToolReasonCode.NON_PYTHON_TASK,
        reason=(
            "当前代码不是 Python，Day 2 的 Python AST 工具不适用。"
            if language is not ProgrammingLanguage.UNKNOWN
            else "当前任务没有可解析的 Python 代码，Day 2 静态工具不适用。"
        ),
    )


def analyze_task(request: TaskCreateRequest) -> TaskAnalysis:
    """Run the frozen v1 compatibility classifier; G5 must not call this."""

    text = request.task_text
    extracted = extract_python(text)
    language = _detect_language(text, extracted)
    task_type = _detect_task_type(text)
    decision = _tool_decision(language, extracted)
    concepts = _detect_concepts(text)
    has_code = language is not ProgrammingLanguage.UNKNOWN or _FENCE in text
    framework = _detect_framework(text)
    domain, confidence, reasons = _classify_domain(
        text=text,
        extracted=extracted,
        language=language,
        framework=framework,
        concepts=concepts,
    )
    if has_code:
        artifact_type = ArtifactType.SOURCE_CODE
    elif task_type is TaskType.ENVIRONMENT_CONFIGURATION:
        artifact_type = ArtifactType.CONFIGURATION
    elif domain is Domain.GENERAL_TEXT:
        artifact_type = ArtifactType.TEXT
    else:
        artifact_type = ArtifactType.NONE
    audience = (
        Audience.BEGINNER
        if any(token in text.lower() for token in ("初学", "新手", "beginner", "入门"))
        else Audience.UNKNOWN
    )
    semantic_parts = [
        f"domain:{domain.value}",
        f"task_type:{task_type.value}",
        f"language:{language.value}",
        *(f"concept:{concept}" for concept in concepts),
    ]
    fingerprint = TaskFingerprint(
        id=new_prefixed_ulid("fp"),
        domain=domain,
        classification_confidence=confidence,
        classification_reasons=reasons,
        task_type=task_type,
        artifact_type=artifact_type,
        audience=audience,
        project_key=None,
        language=language,
        framework=framework,
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


def build_public_plan(
    analysis: TaskAnalysis,
    *,
    selected_count: int = 0,
    injected_count: int = 0,
    memory_mode_off: bool = False,
) -> PublicPlan:
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
    if memory_mode_off:
        memory_summary = "本任务已关闭记忆模式，不会检索或注入历史记忆。"
    elif injected_count:
        memory_summary = f"已选择并注入 {injected_count} 张 owner 隔离的 active 记忆。"
    elif selected_count:
        memory_summary = "已选择适用记忆，但因 Prompt 预算未注入正文。"
    else:
        memory_summary = "本任务未选择可用的 active 记忆，不会注入历史偏好。"
    return PublicPlan(
        id=new_prefixed_ulid("plan"),
        goal=goals[analysis.goal_code],
        memory_summary=memory_summary,
        next_action=next_action,
    )
