"""Day 7 public-account, CSRF, rate-limit, quota, and cascade tests."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from memtrace_api.database import session_scope
from memtrace_api.db_models import (
    DailyTurnQuotaModel,
    IdempotencyKeyModel,
    LocalAccountModel,
    RegistrationInviteModel,
    UserModel,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.public_auth import finish_turn_quota, reserve_turn_quota
from memtrace_api.repositories import UserContext
from memtrace_api.schemas import utc_now


def _seed_invite(client, code: str, *, uses: int = 1) -> None:
    with session_scope(client.app.state.db_session_factory) as session:
        session.add(
            RegistrationInviteModel(
                id=new_prefixed_ulid("invite"),
                code_hash=hashlib.sha256(code.encode()).hexdigest(),
                max_uses=uses,
                use_count=0,
                expires_at=utc_now() + timedelta(hours=1),
                status="active",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )


def _register(client, code: str, username: str = "alice_01") -> dict[str, object]:
    response = client.post(
        "/api/v2/auth/register",
        json={
            "invitation_code": code,
            "username": username.upper(),
            "display_name": " Alice ",
            "password": "correct horse battery staple",
            "password_confirmation": "correct horse battery staple",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _csrf_headers(
    payload: dict[str, object],
    *,
    idempotency_key: str = "day7-auth-write-0001",
) -> dict[str, str]:
    session = payload.get("session", payload)
    assert isinstance(session, dict)
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": str(session["csrf_token"]),
        "Idempotency-Key": idempotency_key,
    }


def test_register_is_atomic_and_recovery_secret_is_one_time(client_factory) -> None:
    client = client_factory(allow_demo_sessions=False, public_origin="http://testserver")
    code = "inv_0123456789012345678901234567890123456789"
    _seed_invite(client, code)
    payload = _register(client, code)
    assert payload["schema_version"] == "2.1.0"
    assert payload["recovery_code"].startswith("rec_")
    assert payload["session"]["account"] == {
        "username": "alice_01",
        "display_name": "Alice",
        "status": "active",
        "default_memory_mode": "on",
    }
    assert payload["session"]["quota"]["remaining"] == 50
    assert "memtrace_session" in client.cookies

    current = client.get("/api/v2/auth/session")
    assert current.status_code == 200
    assert "recovery_code" not in current.text
    with session_scope(client.app.state.db_session_factory) as session:
        account = session.execute(select(LocalAccountModel)).scalar_one()
        assert account.password_hash.startswith("$argon2id$")
        assert "correct horse" not in account.password_hash
        invite = session.execute(select(RegistrationInviteModel)).scalar_one()
        assert invite.status == "exhausted"

    reused = client.post(
        "/api/v2/auth/register",
        json={
            "invitation_code": code,
            "username": "other_user",
            "display_name": "Other",
            "password": "another strong password 123",
            "password_confirmation": "another strong password 123",
        },
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "INVITATION_INVALID"


def test_public_writes_require_exact_origin_and_session_bound_csrf(client_factory) -> None:
    client = client_factory(allow_demo_sessions=False, public_origin="http://testserver")
    code = "inv_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _seed_invite(client, code)
    payload = _register(client, code)

    missing = client.patch("/api/v2/auth/account/preferences", json={"default_memory_mode": "off"})
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "ORIGIN_INVALID"

    bad_origin = client.patch(
        "/api/v2/auth/account/preferences",
        json={"default_memory_mode": "off"},
        headers={"Origin": "https://attacker.invalid", "X-CSRF-Token": "x" * 43},
    )
    assert bad_origin.status_code == 403
    assert bad_origin.json()["error"]["code"] == "ORIGIN_INVALID"

    updated = client.patch(
        "/api/v2/auth/account/preferences",
        json={"default_memory_mode": "off"},
        headers=_csrf_headers(payload),
    )
    assert updated.status_code == 200, updated.text
    assert client.get("/api/v2/auth/session").json()["account"]["default_memory_mode"] == "off"

    replayed = client.patch(
        "/api/v2/auth/account/preferences",
        json={"default_memory_mode": "off"},
        headers=_csrf_headers(payload),
    )
    assert replayed.status_code == 200
    assert replayed.json() == updated.json()

    conflict = client.patch(
        "/api/v2/auth/account/preferences",
        json={"default_memory_mode": "on"},
        headers=_csrf_headers(payload),
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_recovery_rotation_replays_without_plaintext_snapshot(client_factory) -> None:
    client = client_factory(allow_demo_sessions=False, public_origin="http://testserver")
    code = "inv_abababababababababababababababababababab"
    _seed_invite(client, code)
    payload = _register(client, code)
    headers = _csrf_headers(payload, idempotency_key="day7-rotate-recovery-0001")

    first = client.post("/api/v2/auth/recovery-code/rotate", headers=headers)
    second = client.post("/api/v2/auth/recovery-code/rotate", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()

    with session_scope(client.app.state.db_session_factory) as session:
        record = session.execute(
            select(IdempotencyKeyModel).where(
                IdempotencyKeyModel.route == "/api/v2/auth/recovery-code/rotate"
            )
        ).scalar_one()
        assert first.json()["recovery_code"] not in record.response_json
        assert "completed" in record.response_json


def test_login_is_uniform_and_rate_limited_by_username_and_ip(client_factory) -> None:
    client = client_factory(allow_demo_sessions=False, public_origin="http://testserver")
    for index in range(5):
        response = client.post(
            "/api/v2/auth/login",
            json={"username": f"missing_{index}", "password": "wrong password value"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"
    blocked = client.post(
        "/api/v2/auth/login",
        json={"username": "another_user", "password": "wrong password value"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert blocked.json()["error"]["details"]["retry_after_seconds"] > 0


def test_login_rate_limit_uses_forwarded_ip_only_from_exact_trusted_proxy(
    client_factory,
) -> None:
    inner = client_factory(
        allow_demo_sessions=False,
        public_origin="http://testserver",
        trusted_proxy_ips="172.31.247.1",
    ).app
    proxied = ProxyHeadersMiddleware(inner, trusted_hosts=["172.31.247.1"])

    first_user = TestClient(
        proxied,
        client=("172.31.247.1", 50000),
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    second_user = TestClient(
        proxied,
        client=("172.31.247.1", 50001),
        headers={"X-Forwarded-For": "203.0.113.11"},
    )
    for index in range(5):
        response = first_user.post(
            "/api/v2/auth/login",
            json={"username": f"proxy_missing_{index}", "password": "wrong password value"},
        )
        assert response.status_code == 401

    independent = second_user.post(
        "/api/v2/auth/login",
        json={"username": "proxy_other_user", "password": "wrong password value"},
    )
    assert independent.status_code == 401

    untrusted = ProxyHeadersMiddleware(inner, trusted_hosts=["172.31.247.1"])
    untrusted_client = TestClient(
        untrusted,
        client=("198.51.100.20", 51000),
    )
    for index in range(5):
        response = untrusted_client.post(
            "/api/v2/auth/login",
            headers={"X-Forwarded-For": f"192.0.2.{index + 1}"},
            json={"username": f"spoof_missing_{index}", "password": "wrong password value"},
        )
        assert response.status_code == 401

    spoof_blocked = untrusted_client.post(
        "/api/v2/auth/login",
        headers={"X-Forwarded-For": "192.0.2.200"},
        json={"username": "spoof_other_user", "password": "wrong password value"},
    )
    assert spoof_blocked.status_code == 429
    assert spoof_blocked.json()["error"]["code"] == "RATE_LIMITED"


def test_recovery_rotates_code_and_revokes_old_session(client_factory) -> None:
    client = client_factory(allow_demo_sessions=False, public_origin="http://testserver")
    code = "inv_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    _seed_invite(client, code)
    payload = _register(client, code)
    recovery_code = payload["recovery_code"]
    old_cookie = client.cookies.get("memtrace_session")

    recovered = client.post(
        "/api/v2/auth/recover",
        json={
            "username": "alice_01",
            "recovery_code": recovery_code,
            "new_password": "new correct horse battery staple",
            "new_password_confirmation": "new correct horse battery staple",
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["recovery_code"] != recovery_code
    assert recovered.json()["sessions_revoked"] == 1

    client.cookies.set("memtrace_session", old_cookie)
    assert client.get("/api/v2/auth/session").status_code == 401
    login = client.post(
        "/api/v2/auth/login",
        json={"username": "alice_01", "password": "new correct horse battery staple"},
    )
    assert login.status_code == 200, login.text


def test_quota_is_atomic_and_failed_attempts_remain_consumed(client_factory) -> None:
    client = client_factory(
        allow_demo_sessions=False,
        public_origin="http://testserver",
        daily_real_turn_limit=2,
    )
    code = "inv_cccccccccccccccccccccccccccccccccccccccc"
    _seed_invite(client, code)
    payload = _register(client, code)
    owner_id = None
    with session_scope(client.app.state.db_session_factory) as session:
        owner_id = session.execute(select(LocalAccountModel.owner_id)).scalar_one()
    user_ctx = UserContext(
        user_id=owner_id,
        demo_alias=f"account_{owner_id}",
        auth_kind="public",
        username="alice_01",
    )
    reserve_turn_quota(client.app.state.db_session_factory, client.app.state.settings, user_ctx)
    concurrent = None
    try:
        reserve_turn_quota(client.app.state.db_session_factory, client.app.state.settings, user_ctx)
    except Exception as exc:  # exact public error is asserted below
        concurrent = exc
    assert getattr(concurrent, "code", None).value == "CONCURRENT_TURN_LIMIT"
    finish_turn_quota(client.app.state.db_session_factory, client.app.state.settings, user_ctx)
    reserve_turn_quota(client.app.state.db_session_factory, client.app.state.settings, user_ctx)
    finish_turn_quota(client.app.state.db_session_factory, client.app.state.settings, user_ctx)
    exhausted = None
    try:
        reserve_turn_quota(client.app.state.db_session_factory, client.app.state.settings, user_ctx)
    except Exception as exc:
        exhausted = exc
    assert getattr(exhausted, "code", None).value == "QUOTA_EXHAUSTED"
    with session_scope(client.app.state.db_session_factory) as session:
        quota = session.execute(select(DailyTurnQuotaModel)).scalar_one()
        assert (quota.used_turns, quota.active_turns) == (2, 0)
    assert payload["session"]["quota"]["limit"] == 2


def test_account_delete_cascades_owner_data(client_factory) -> None:
    client = client_factory(allow_demo_sessions=False, public_origin="http://testserver")
    code = "inv_dddddddddddddddddddddddddddddddddddddddd"
    _seed_invite(client, code)
    payload = _register(client, code)
    deleted = client.request(
        "DELETE",
        "/api/v2/auth/account",
        json={
            "current_password": "correct horse battery staple",
            "confirm_username": "alice_01",
        },
        headers=_csrf_headers(payload),
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "account_deleted"
    assert client.get("/api/v2/auth/session").status_code == 401
    with session_scope(client.app.state.db_session_factory) as session:
        assert session.execute(select(func.count()).select_from(UserModel)).scalar_one() == 0
