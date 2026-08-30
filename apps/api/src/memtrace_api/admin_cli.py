"""Minimal release administration CLI for invites and local accounts."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
import unicodedata
from datetime import timedelta

from sqlalchemy import and_, select, text, update

from memtrace_api.config import get_settings
from memtrace_api.database import create_db_engine, create_session_factory, session_scope
from memtrace_api.db_models import (
    DemoSessionModel,
    LocalAccountModel,
    RegistrationInviteModel,
)
from memtrace_api.ids import new_prefixed_ulid
from memtrace_api.readiness import DatabaseRevisionError, ensure_database_current
from memtrace_api.schemas import utc_now


def _normalize_username(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MemTrace release account administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    invite_create = subparsers.add_parser(
        "invite-create", help="create an invite and print its secret once"
    )
    invite_create.add_argument("--max-uses", type=int, default=1, choices=range(1, 101))
    invite_create.add_argument("--expires-hours", type=int, default=24 * 7)

    subparsers.add_parser("invite-list", help="list invite metadata without hashes or secrets")
    subparsers.add_parser("account-list", help="list account metadata")

    for name in ("account-disable", "account-enable", "sessions-revoke"):
        command = subparsers.add_parser(name)
        command.add_argument("username")
    return parser


def _require_current_database(factory) -> str:
    with session_scope(factory) as session:
        return ensure_database_current(session)


def _create_invite(factory, *, max_uses: int, expires_hours: int) -> dict[str, object]:
    if expires_hours < 1 or expires_hours > 24 * 365:
        raise ValueError("--expires-hours must be between 1 and 8760")
    code = "inv_" + secrets.token_urlsafe(32)
    now = utc_now()
    invite_id = new_prefixed_ulid("invite")
    expires_at = now + timedelta(hours=expires_hours)
    with session_scope(factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(
            RegistrationInviteModel(
                id=invite_id,
                code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
                max_uses=max_uses,
                use_count=0,
                expires_at=expires_at,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
    return {
        "invite_id": invite_id,
        "invitation_code": code,
        "max_uses": max_uses,
        "expires_at": expires_at.isoformat(),
        "notice": "invitation_code is shown once; store it securely",
    }


def _list_invites(factory) -> list[dict[str, object]]:
    with session_scope(factory) as session:
        rows = session.execute(
            select(RegistrationInviteModel).order_by(RegistrationInviteModel.created_at.desc())
        ).scalars()
        return [
            {
                "invite_id": row.id,
                "status": row.status,
                "use_count": row.use_count,
                "max_uses": row.max_uses,
                "expires_at": row.expires_at.isoformat(),
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]


def _list_accounts(factory) -> list[dict[str, object]]:
    with session_scope(factory) as session:
        rows = session.execute(
            select(LocalAccountModel).order_by(LocalAccountModel.created_at.asc())
        ).scalars()
        return [
            {
                "username": row.username_normalized,
                "display_name": row.display_name,
                "status": row.status,
                "default_memory_mode": row.default_memory_mode,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]


def _account_action(factory, *, username: str, action: str) -> dict[str, object]:
    normalized = _normalize_username(username)
    with session_scope(factory) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        account = session.execute(
            select(LocalAccountModel).where(LocalAccountModel.username_normalized == normalized)
        ).scalar_one_or_none()
        if account is None:
            raise LookupError("account not found")
        now = utc_now()
        if action == "account-enable":
            account.status = "active"
        elif action == "account-disable":
            account.status = "disabled"
        account.updated_at = now
        revoked = 0
        if action in {"account-disable", "sessions-revoke"}:
            result = session.execute(
                update(DemoSessionModel)
                .where(
                    and_(
                        DemoSessionModel.owner_id == account.owner_id,
                        DemoSessionModel.auth_kind == "public",
                        DemoSessionModel.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=now, revoked_reason=action.replace("-", "_"))
            )
            revoked = result.rowcount or 0
    return {
        "username": normalized,
        "status": account.status,
        "sessions_revoked": revoked,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    engine = create_db_engine(settings.memtrace_database_url)
    factory = create_session_factory(engine)
    try:
        revision = _require_current_database(factory)
        if args.command == "invite-create":
            payload = _create_invite(
                factory,
                max_uses=args.max_uses,
                expires_hours=args.expires_hours,
            )
        elif args.command == "invite-list":
            payload = {"invites": _list_invites(factory)}
        elif args.command == "account-list":
            payload = {"accounts": _list_accounts(factory)}
        else:
            payload = _account_action(factory, username=args.username, action=args.command)
        _print({"migration_revision": revision, **payload})
        return 0
    except (DatabaseRevisionError, ValueError, LookupError) as exc:
        _print({"error": type(exc).__name__, "message": str(exc)})
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
