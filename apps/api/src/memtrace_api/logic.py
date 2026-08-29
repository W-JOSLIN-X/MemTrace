"""Deterministic tool-decision logic.

v2 note: analyze_task() still exists for backward compatibility, but the
auto_rule_v1 keyword classification (domain, task_type, artifact_type,
audience, framework, concepts, semantic_query) has been removed from the
product semantic chain.  Those fingerprint fields are populated with
neutral legacy values only — they are persisted for debugging and
migration compatibility, but they no longer drive memory retrieval,
injection decisions, or any product behavior.

The only product-relevant output of analyze_task() is the tool_decision
(whether to call python_ast_check).
"""

from __future__ import annotations

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


def analyze_task(request: TaskCreateRequest) -> TaskAnalysis:
    """Analyze a task creation request.

    v2: Only the tool_decision (python_ast_check eligibility) drives
    product behavior.  All fingerprint classification fields (domain,
    task_type, artifact_type, etc.) are set to neutral legacy values.
    """
    text = request.task_text
    extracted = extract_python(text)
    language = ProgrammingLanguage.PYTHON if extracted is not None else ProgrammingLanguage.UNKNOWN
    decision = _tool_decision(language, extracted)

    # Neutral legacy values — persisted for backward compatibility but
    # no longer used for memory retrieval or product decisions.
    fingerprint = TaskFingerprint(
        id=new_prefixed_ulid("fp"),
        domain=Domain.OTHER,
        classification_confidence=0.0,
        classification_reasons=[],
        task_type=TaskType.GENERAL_QUESTION,
        artifact_type=ArtifactType.NONE,
        audience=Audience.UNKNOWN,
        project_key=None,
        language=language,
        framework=None,
        concepts=[],
        tool_context=["python_ast_check"] if decision.action is ToolAction.CALL else [],
        current_constraints=request.current_constraints,
        semantic_query="legacy",
    )
    goal_code = "analyze_code" if extracted is not None else "answer_question"
    return TaskAnalysis(
        fingerprint=fingerprint,
        tool_decision=decision,
        extracted_python=extracted,
        goal_code=goal_code,
        next_action_code=(
            "python_ast_check" if decision.action is ToolAction.CALL else "generate_directly"
        ),
    )


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
        reason="当前任务没有可解析的 Python 代码，Day 2 静态工具不适用。",
    )


def build_public_plan(
    analysis: TaskAnalysis,
    *,
    selected_count: int = 0,
    injected_count: int = 0,
    memory_mode_off: bool = False,
) -> PublicPlan:
    """Build a simple public plan from analysis.

    v2: No longer driven by auto_rule_v1 classification.  Plan is a
    simple metadata dict describing the current turn's goal and action.
    """
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
