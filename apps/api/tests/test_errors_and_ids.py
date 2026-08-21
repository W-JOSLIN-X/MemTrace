from __future__ import annotations

import json
import re
from collections.abc import Callable

from fastapi import Query
from fastapi.testclient import TestClient

from memtrace_api.config import PROJECT_ROOT
from memtrace_api.errors import ErrorCode
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.main import create_app

ID_PATTERN = re.compile(r"^[a-z]+_[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def test_prefixed_ulid_matches_contract() -> None:
    values = {new_prefixed_ulid("req") for _ in range(100)}
    assert len(values) == 100
    assert all(ID_PATTERN.fullmatch(value) for value in values)


def test_invalid_ulid_prefix_is_rejected() -> None:
    for prefix in ("", "request-id", "请求"):
        try:
            new_prefixed_ulid(prefix)
        except ValueError:
            continue
        raise AssertionError(f"prefix should be rejected: {prefix!r}")


def test_error_code_enum_exactly_matches_contract() -> None:
    contract_path = PROJECT_ROOT / "contracts" / "schemas" / "g0-api.schema.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert [code.value for code in ErrorCode] == contract["$defs"]["ErrorCode"]["enum"]


def test_validation_errors_use_public_envelope(
    client_factory: Callable[..., TestClient],
) -> None:
    app = create_app(client_factory().app.state.settings)

    @app.get("/_test/validated")
    async def validated(value: int = Query(ge=1)) -> dict[str, int]:
        return {"value": value}

    response = TestClient(app).get("/_test/validated?value=0")
    body = response.json()
    assert response.status_code == 422
    assert response.headers["x-request-id"] == body["error"]["request_id"]
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["retryable"] is False
    assert "input" not in body["error"]["details"]["field_errors"][0]


def test_unexpected_errors_use_safe_public_envelope(
    client_factory: Callable[..., TestClient],
) -> None:
    app = create_app(client_factory().app.state.settings)

    @app.get("/_test/failure")
    async def failure() -> None:
        raise RuntimeError("private diagnostic")

    response = TestClient(app, raise_server_exceptions=False).get("/_test/failure")
    body = response.json()
    assert response.status_code == 500
    assert response.headers["x-request-id"] == body["error"]["request_id"]
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "private diagnostic" not in response.text
