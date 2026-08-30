"""Deterministic, non-executing static tool registry for G0."""

from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass
from typing import Literal

from memtrace_api.schemas import (
    AstSyntaxError,
    AsyncErrorCode,
    CodeSource,
    PythonAstResult,
    ToolArgsSummary,
)

MAX_TOOL_INPUT_BYTES = 102_400
_PYTHON_FENCE = re.compile(
    r"```(?:python|py)[ \t]*\r?\n(?P<code>.*?)```",
    flags=re.IGNORECASE | re.DOTALL,
)
_WHOLE_TASK_CODE_CUE = re.compile(
    r"[=()\[\]{}:]|\b(?:def|class|import|from|for|while|if|try|with|return|lambda|print)\b"
)


@dataclass(frozen=True, slots=True)
class ExtractedPython:
    code: str
    source: CodeSource
    code_block_id: str = "code_001"

    @property
    def byte_count(self) -> int:
        return len(self.code.encode("utf-8"))

    @property
    def summary(self) -> ToolArgsSummary:
        return ToolArgsSummary(code_source=self.source, code_bytes=self.byte_count)


@dataclass(frozen=True, slots=True)
class ToolExecution:
    status: Literal["succeeded", "failed"]
    result: PythonAstResult | None
    latency_ms: float


class ToolFailure(Exception):
    def __init__(self, code: AsyncErrorCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def extract_python(task_text: str) -> ExtractedPython | None:
    """Use the first Python fence, otherwise accept only a wholly valid Python task."""

    candidates = extract_python_candidates(task_text)
    return candidates[0] if candidates else None


def extract_python_candidates(task_text: str) -> list[ExtractedPython]:
    """Enumerate bounded Python candidates without making a semantic tool decision."""

    candidates: list[ExtractedPython] = []
    for index, fenced in enumerate(_PYTHON_FENCE.finditer(task_text), start=1):
        if index > 8:
            break
        code = fenced.group("code")
        if not code.strip() or len(code.encode()) > MAX_TOOL_INPUT_BYTES:
            continue
        candidates.append(
            ExtractedPython(
                code=code,
                source=CodeSource.FENCED_PYTHON,
                code_block_id=f"code_{index:03d}",
            )
        )
    if candidates:
        return candidates

    candidate = task_text.strip()
    if not candidate or len(candidate.encode("utf-8")) > MAX_TOOL_INPUT_BYTES:
        return []
    # A plain natural-language word can be a valid Python identifier. Requiring
    # a code-shaped cue prevents such prompts from being misclassified and sent
    # to the AST tool while preserving whole-snippet support.
    if _WHOLE_TASK_CODE_CUE.search(candidate) is None:
        return []
    try:
        ast.parse(candidate)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return []
    return [
        ExtractedPython(
            code=candidate,
            source=CodeSource.WHOLE_TASK_VALID_PYTHON,
            code_block_id="code_001",
        )
    ]


def _positive(value: int | None) -> int | None:
    return value if value is not None and value >= 1 else None


def python_ast_check(extracted: ExtractedPython) -> PythonAstResult:
    """Parse Python syntax only; no source is run, imported, read, written, or sent anywhere."""

    byte_count = extracted.byte_count
    if byte_count < 1 or byte_count > MAX_TOOL_INPUT_BYTES:
        raise ToolFailure(
            AsyncErrorCode.TOOL_INPUT_INVALID,
            "Python 静态检查输入大小不合法。",
        )
    try:
        ast.parse(extracted.code)
    except SyntaxError as exc:
        safe_message = " ".join(str(exc.msg).split())[:200] or "Python 语法无效"
        return PythonAstResult(
            valid=False,
            syntax_error=AstSyntaxError(
                message=safe_message,
                line=_positive(exc.lineno),
                column=_positive(exc.offset),
                end_line=_positive(exc.end_lineno),
                end_column=_positive(exc.end_offset),
            ),
        )
    except (ValueError, TypeError, MemoryError, RecursionError) as exc:
        raise ToolFailure(
            AsyncErrorCode.TOOL_INPUT_INVALID,
            "Python 静态检查无法处理该输入。",
        ) from exc
    return PythonAstResult(valid=True, syntax_error=None)


class ToolRegistry:
    """Hard-coded allowlist; G0 contains exactly one read-only static tool."""

    registered_names = frozenset({"python_ast_check"})

    def run(self, tool_name: str, extracted: ExtractedPython) -> ToolExecution:
        if tool_name not in self.registered_names:
            raise ToolFailure(AsyncErrorCode.TOOL_NOT_FOUND, "请求的工具未在白名单中。")
        started = time.perf_counter()
        result = python_ast_check(extracted)
        return ToolExecution(
            status="succeeded",
            result=result,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
