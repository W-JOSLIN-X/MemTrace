"""Strict Day 7 public-release request and response contracts."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from memtrace_api.errors import ContractModel
from memtrace_api.schemas import EffectiveMemoryMode, ProviderMode, RequestId, TaskId

PUBLIC_CONTRACT_VERSION = "2.1.0"

Username = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9_]{3,32}$", min_length=3, max_length=32),
]
DisplayName = Annotated[str, StringConstraints(min_length=1, max_length=80)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]
SecretCode = Annotated[str, StringConstraints(min_length=20, max_length=256)]


def normalize_username(value: str) -> str:
    """Apply the normative NFKC + casefold username normalization."""

    return unicodedata.normalize("NFKC", value).casefold().strip()


class RegisterRequest(ContractModel):
    invitation_code: SecretCode
    username: Username
    display_name: DisplayName
    password: Password
    password_confirmation: Password

    @field_validator("username", mode="before")
    @classmethod
    def normalized_username(cls, value: object) -> object:
        return normalize_username(value) if isinstance(value, str) else value

    @field_validator("display_name", mode="before")
    @classmethod
    def normalized_display_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return " ".join(unicodedata.normalize("NFKC", value).strip().split())

    @model_validator(mode="after")
    def passwords_match(self) -> RegisterRequest:
        if self.password != self.password_confirmation:
            raise ValueError("password confirmation does not match")
        return self


class LoginRequest(ContractModel):
    username: Username
    password: Password

    @field_validator("username", mode="before")
    @classmethod
    def normalized_username(cls, value: object) -> object:
        return normalize_username(value) if isinstance(value, str) else value


class RecoverRequest(ContractModel):
    username: Username
    recovery_code: SecretCode
    new_password: Password
    new_password_confirmation: Password

    @field_validator("username", mode="before")
    @classmethod
    def normalized_username(cls, value: object) -> object:
        return normalize_username(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def passwords_match(self) -> RecoverRequest:
        if self.new_password != self.new_password_confirmation:
            raise ValueError("password confirmation does not match")
        return self


class ChangePasswordRequest(ContractModel):
    current_password: Password
    new_password: Password
    new_password_confirmation: Password

    @model_validator(mode="after")
    def validate_password_change(self) -> ChangePasswordRequest:
        if self.new_password != self.new_password_confirmation:
            raise ValueError("password confirmation does not match")
        if self.current_password == self.new_password:
            raise ValueError("new password must differ from current password")
        return self


class DeleteAccountRequest(ContractModel):
    current_password: Password
    confirm_username: Username

    @field_validator("confirm_username", mode="before")
    @classmethod
    def normalized_username(cls, value: object) -> object:
        return normalize_username(value) if isinstance(value, str) else value


class AccountPreferencesRequest(ContractModel):
    default_memory_mode: EffectiveMemoryMode


class AccountProjection(ContractModel):
    username: Username
    display_name: DisplayName
    status: Literal["active"]
    default_memory_mode: EffectiveMemoryMode


class QuotaProjection(ContractModel):
    limit: int = Field(ge=1)
    used: int = Field(ge=0)
    remaining: int = Field(ge=0)
    active: int = Field(ge=0)
    resets_at: datetime


class AuthSessionResponse(ContractModel):
    schema_version: Literal["2.1.0"] = "2.1.0"
    request_id: RequestId
    authenticated: Literal[True] = True
    account: AccountProjection
    csrf_token: Annotated[str, StringConstraints(min_length=43, max_length=128)]
    session_expires_at: datetime
    quota: QuotaProjection
    provider_mode: ProviderMode
    model: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    key_configured: bool


class RegisterResponse(ContractModel):
    schema_version: Literal["2.1.0"] = "2.1.0"
    request_id: RequestId
    session: AuthSessionResponse
    recovery_code: SecretCode


class RecoveryResponse(ContractModel):
    schema_version: Literal["2.1.0"] = "2.1.0"
    request_id: RequestId
    recovery_code: SecretCode
    sessions_revoked: int = Field(ge=0)


class RecoveryCodeResponse(ContractModel):
    schema_version: Literal["2.1.0"] = "2.1.0"
    request_id: RequestId
    recovery_code: SecretCode


class AuthActionResponse(ContractModel):
    schema_version: Literal["2.1.0"] = "2.1.0"
    request_id: RequestId
    status: Literal[
        "logged_out",
        "all_sessions_revoked",
        "password_changed",
        "account_deleted",
        "preferences_updated",
    ]


class SystemResponse(ContractModel):
    schema_version: Literal["2.1.0"] = "2.1.0"
    request_id: RequestId
    version: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    revision: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    migration: Literal["007_day7_public_release"]
    provider_mode: ProviderMode
    model: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    key_configured: bool
    memory_budget_per_card: int = Field(ge=1)
    memory_budget_total: int = Field(ge=1)
    tool_allowlist: Annotated[
        list[Literal["python_ast_check"]], Field(min_length=1, max_length=1)
    ] = Field(default_factory=lambda: ["python_ast_check"])
    quota: QuotaProjection


class ConversationListItem(ContractModel):
    task_id: TaskId
    title: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    memory_mode: EffectiveMemoryMode
    message_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(ContractModel):
    schema_version: Literal["2.1.0"] = "2.1.0"
    request_id: RequestId
    items: Annotated[list[ConversationListItem], Field(max_length=100)]
    next_cursor: TaskId | None = None
