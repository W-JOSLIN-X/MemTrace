from __future__ import annotations

import pytest

from memtrace_api.schemas import AsyncErrorCode, CodeSource
from memtrace_api.tools import (
    ExtractedPython,
    ToolFailure,
    ToolRegistry,
    extract_python,
    python_ast_check,
)


def test_first_python_fence_is_extracted_and_invalid_syntax_is_a_result() -> None:
    extracted = extract_python("before\n```python\ndef broken(:\n    pass\n```\n```py\nx = 1\n```")
    assert extracted is not None
    assert extracted.source is CodeSource.FENCED_PYTHON
    assert "broken" in extracted.code
    result = python_ast_check(extracted)
    assert result.valid is False
    assert result.syntax_error is not None
    assert result.syntax_error.line == 1
    assert not hasattr(result.syntax_error, "text")


def test_whole_task_must_be_valid_python() -> None:
    valid = extract_python("value = [item * 2 for item in range(3)]")
    assert valid is not None
    assert valid.source is CodeSource.WHOLE_TASK_VALID_PYTHON
    assert python_ast_check(valid).valid is True
    assert extract_python("def invalid(:") is None
    assert extract_python("帮我处理一下") is None


def test_blank_python_fence_is_not_a_tool_input() -> None:
    assert extract_python("```python\n   \n```") is None


def test_tool_registry_rejects_every_unknown_name() -> None:
    registry = ToolRegistry()
    assert registry.registered_names == {"python_ast_check"}
    extracted = ExtractedPython(code="x = 1", source=CodeSource.WHOLE_TASK_VALID_PYTHON)
    with pytest.raises(ToolFailure) as caught:
        registry.run("python_run", extracted)
    assert caught.value.code is AsyncErrorCode.TOOL_NOT_FOUND


def test_tool_rejects_input_over_100_kib() -> None:
    extracted = ExtractedPython(
        code="x" * 102_401,
        source=CodeSource.FENCED_PYTHON,
    )
    with pytest.raises(ToolFailure) as caught:
        python_ast_check(extracted)
    assert caught.value.code is AsyncErrorCode.TOOL_INPUT_INVALID


def test_ast_recursion_failure_is_safely_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_parse(source: str) -> None:
        del source
        raise RecursionError

    monkeypatch.setattr("memtrace_api.tools.ast.parse", fail_parse)
    assert extract_python("x = 1") is None
    extracted = ExtractedPython(code="x = 1", source=CodeSource.WHOLE_TASK_VALID_PYTHON)
    with pytest.raises(ToolFailure) as caught:
        python_ast_check(extracted)
    assert caught.value.code is AsyncErrorCode.TOOL_INPUT_INVALID
